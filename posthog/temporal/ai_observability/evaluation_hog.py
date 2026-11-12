import json
from typing import Any

import structlog
import temporalio
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_errors import (
    require_user_error_spec,
    status_reason_detail_for_terminal_user_error,
    truncate_error_detail,
)
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult, build_skipped_evaluation_result
from posthog.temporal.ai_observability.metrics import increment_user_errors

from products.ai_observability.backend.facade.evaluation_runtime import (
    build_hog_event_global,
    coerce_hog_io_value,
    execute_hog_eval_bytecode,
    extract_event_io,
    hog_bytecode_references_global,
)
from products.ai_observability.backend.models.evaluation_configs import NumericOutputConfig

logger = structlog.get_logger(__name__)


def finalize_hog_eval_result(
    result: dict[str, Any], *, evaluation: dict[str, Any], allows_na: bool, unit_label: str | None
) -> EvaluationActivityResult:
    """Turn raw Hog bytecode output into an activity result.

    Shared by the generation, trace, and session Hog activities: this is the block that decides
    whether a failure is our bug, this unit's data, or a broken evaluation, and a drifted copy
    would mean a broken evaluation silently retrying against every unit instead of disabling
    itself. `unit_label` ("trace" / "session") reaches only the raised our-bug message, so whoever
    triages the page can tell which target produced it; the generation path passes None to keep its
    message, and so the error tracking issue it groups into, unchanged.
    """
    if result["error"]:
        if result.get("unexpected"):
            # A genuine bug in our evaluation code (not the user's Hog). Raise so the Temporal
            # interceptor reports it to error tracking and we get paged to investigate.
            qualifier = f" ({unit_label})" if unit_label else ""
            raise ApplicationError(
                f"Hog evaluation error{qualifier}: {result['error']}",
                non_retryable=True,
            )

        if result.get("user_input_error"):
            # This unit's data was not the shape the Hog source expected. Deliberately not marked
            # terminal: the same evaluation usually reads the next unit fine, so disabling it over
            # one malformed payload would cost the user every later result. Skipping keeps the
            # evaluation running and leaves the run visible as skipped rather than failed.
            input_error_spec = require_user_error_spec(result.get("skip_reason", "hog_input_error"))
            increment_user_errors(input_error_spec.error_type)
            # This path raises nothing and emails nobody, and the counter can't carry ids at this
            # cardinality, so without these fields there is no way to find the offending evaluation.
            logger.warning(
                "Hog eval could not handle unit data",
                team_id=evaluation.get("team_id"),
                evaluation_id=evaluation.get("id"),
                unit=unit_label or "generation",
                error=result["error"],
            )
            detail = truncate_error_detail(result["error"])
            # Lead with the user-facing message; detail may contain a Python exception.
            return build_skipped_evaluation_result(
                output_type=evaluation.get("output_type", "boolean"),
                allows_na=allows_na,
                reasoning=f"{input_error_spec.safe_message} ({detail})" if detail else input_error_spec.safe_message,
                skip_reason=input_error_spec.error_type,
            )

        # The user's Hog source itself errored — an expected outcome of running customer-authored
        # code, recorded as a skipped evaluation rather than raised (which would flood error
        # tracking with one event per unit). Marked terminal so the workflow disables the broken
        # eval instead of re-running it against every matching unit (mirrors the generation path).
        spec = require_user_error_spec("hog_error")
        error_detail = status_reason_detail_for_terminal_user_error(spec, result["error"]) or spec.safe_message
        return {
            **build_skipped_evaluation_result(
                output_type=evaluation.get("output_type", "boolean"),
                allows_na=allows_na,
                reasoning=error_detail,
                skip_reason="hog_error",
            ),
            "terminal_user_error": True,
            "status_reason": spec.status_reason,
        }

    activity_result: EvaluationActivityResult = {
        "result_type": "boolean",
        "reasoning": result["reasoning"],
        "allows_na": allows_na,
    }
    if evaluation.get("output_type") == "categorical":
        activity_result["result_type"] = "categorical"
        if "categories" in result:
            activity_result["categories"] = result["categories"]
    elif evaluation.get("output_type") == "numeric":
        activity_result["result_type"] = "numeric"
        if "score" in result:
            config = NumericOutputConfig.model_validate(evaluation.get("output_config") or {})
            activity_result["score"] = config.validate_score(result["score"])
            if config.min is not None:
                activity_result["score_min"] = config.min
            if config.max is not None:
                activity_result["score_max"] = config.max
    else:
        activity_result["verdict"] = result["verdict"]
    if allows_na:
        activity_result["applicable"] = result.get("applicable", True)
    return activity_result


def run_hog_eval(
    bytecode: list,
    event_data: dict[str, Any],
    allows_na: bool = False,
    *,
    output_type: str = "boolean",
    output_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run compiled Hog bytecode against a single event.

    Used by both the Temporal activity and the test endpoint.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}.
    Numeric success replaces `verdict` with a validated `score`.
    When allows_na=True, a `return null` is treated as N/A (not an error).
    Sets "user_input_error": True when this event's data defeated the user's Hog source, and
    "unexpected": True only when the bytecode raised something other than a HogVM error or one of
    `HOG_INPUT_ERROR_TYPES` — i.e. a bug in our code rather than in the user's Hog source or its
    input.
    """
    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    event_type = event_data["event"]
    io = extract_event_io(event_type, properties)

    globals_dict: dict[str, Any] = {
        # Generation-only compatibility globals kept for saved Hog source.
        "input": coerce_hog_io_value(io.input_raw),
        "output": coerce_hog_io_value(io.output_raw),
        "properties": properties,
        "event": {
            "uuid": event_data.get("uuid", ""),
            "event": event_type,
            "distinct_id": event_data.get("distinct_id", ""),
        },
    }
    if hog_bytecode_references_global(bytecode, "target"):
        globals_dict["target"] = {
            "type": "generation",
            "id": event_data.get("uuid", ""),
            "total_cost_usd": properties.get("$ai_total_cost_usd"),
            "total_latency_seconds": properties.get("$ai_latency"),
        }
    if hog_bytecode_references_global(bytecode, "evaluation_events"):
        globals_dict["evaluation_events"] = [
            build_hog_event_global(
                event_type,
                properties,
                event_uuid=event_data.get("uuid", ""),
                timestamp=event_data.get("timestamp"),
            )
        ]

    return execute_hog_eval_bytecode(
        bytecode, globals_dict, allows_na=allows_na, output_type=output_type, output_config=output_config
    )


async def run_hog_eval_for_event(evaluation: dict[str, Any], event_data: dict[str, Any]) -> EvaluationActivityResult:
    """Execute Hog code to evaluate the target event."""
    if evaluation["evaluation_type"] != "hog":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    evaluation_config = evaluation.get("evaluation_config", {})
    bytecode = evaluation_config.get("bytecode")
    if not bytecode:
        raise ApplicationError("Missing bytecode in evaluation_config", non_retryable=True)

    output_config = evaluation.get("output_config", {})
    allows_na = output_config.get("allows_na", False)

    def _execute() -> dict[str, Any]:
        return run_hog_eval(
            bytecode,
            event_data,
            allows_na=allows_na,
            output_type=evaluation.get("output_type", "boolean"),
            output_config=output_config,
        )

    result = await database_sync_to_async(_execute, thread_sensitive=False)()

    return finalize_hog_eval_result(result, evaluation=evaluation, allows_na=allows_na, unit_label=None)


@temporalio.activity.defn
async def execute_hog_eval_activity(evaluation: dict[str, Any], event_data: dict[str, Any]) -> EvaluationActivityResult:
    """Execute Hog code to evaluate the target event."""
    return await run_hog_eval_for_event(evaluation, event_data)

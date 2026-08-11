import json
from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio.exceptions import ApplicationError

from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_errors import (
    require_user_error_spec,
    status_reason_detail_for_terminal_user_error,
    truncate_error_detail,
)
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.message_utils import extract_text_from_messages
from posthog.temporal.ai_observability.metrics import increment_user_errors

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import Operation
from common.hogvm.python.utils import HogVMException, HogVMMemoryExceededException, HogVMRuntimeExceededException

logger = structlog.get_logger(__name__)

# Python-level errors the Hog standard library raises when a unit's data is not the shape the
# evaluation source assumed: `ilike` against a list rather than a string, `jsonParse` on truncated
# model output, a divide by a token count that arrived as zero. The evaluation is not broken and
# neither are we, so these skip the one unit instead of paging us or disabling the evaluation.
#
# Classifying by Python type cannot separate a bad value from a source that always fails the same
# way, so a source hardcoded to raise one of these (`length(5)`) still skips every unit. Closing
# that needs an every-unit-skipped signal, not a narrower list. Two exclusions we can make here:
#
# - `ValueError` at large, with `json.JSONDecodeError` (a subclass) listed instead: our own code
#   raises plain ValueError, and skipping on that would hide real bugs.
# - `IndexError`, which no user data reaches: Hog indexing is bounds-safe (`get_nested_value`
#   returns null past the end of an array). What does raise it is an STL call compiled with the
#   wrong arity, which nothing validates at save time, so a source like `jsonParse()` reaches the
#   VM and fails on every unit. Listing it here would skip that source silently and forever, and
#   blame the customer's data for it; left out, it stays loud.
HOG_INPUT_ERROR_TYPES: tuple[type[Exception], ...] = (
    TypeError,
    AttributeError,
    KeyError,
    ZeroDivisionError,
    json.JSONDecodeError,
)


def coerce_hog_io_value(value: Any) -> str:
    """Coerce an extracted input/output value into a string for Hog globals.

    String operations (ilike, length, etc.) should work consistently; users can still
    parse structured data with jsonParse() when needed.
    """
    if isinstance(value, list | dict):
        return json.dumps(value)
    return "" if value is None or value == "" else str(value)


def _extract_hog_message_text(messages: Any) -> str:
    if messages is None or isinstance(messages, str | list | dict):
        return extract_text_from_messages(messages)
    return str(messages)


def _get_hog_output_choice_content(choice: dict[str, Any]) -> Any:
    for key in ("content", "refusal", "text"):
        value = choice.get(key)
        if value is None or (isinstance(value, str | list | dict) and not value):
            continue
        return value
    return None


def _normalize_hog_output_choice(choice: dict[str, Any]) -> dict[str, Any] | None:
    message = choice.get("message")
    if isinstance(message, dict):
        choice = message

    if not any(key in choice for key in ("content", "refusal", "text", "tool_calls")):
        return choice

    content = _get_hog_output_choice_content(choice)
    if content is None and not choice.get("tool_calls"):
        return None
    if content is not None and not isinstance(content, str | list | dict):
        content = coerce_hog_io_value(content)
    return {"content": content, "tool_calls": choice.get("tool_calls")}


def _extract_hog_output_text(output: Any) -> str:
    if isinstance(output, dict) and isinstance(output.get("choices"), list):
        output = output["choices"]

    messages: list[Any] = []
    for choice in output if isinstance(output, list) else [output]:
        if isinstance(choice, dict):
            choice = _normalize_hog_output_choice(choice)
            if choice is None:
                continue
        elif not isinstance(choice, str):
            choice = coerce_hog_io_value(choice)
        messages.append(choice)
    return _extract_hog_message_text(messages)


def hog_bytecode_references_global(bytecode: list[Any], global_name: str) -> bool:
    """Return whether compiled Hog bytecode reads a specific global."""
    return any(
        operation == Operation.GET_GLOBAL and index > 0 and bytecode[index - 1] == global_name
        for index, operation in enumerate(bytecode)
    )


def build_hog_event_global(
    event_type: str,
    properties: dict[str, Any],
    *,
    event_uuid: Any,
    timestamp: Any,
    include_text: bool = True,
) -> dict[str, Any]:
    """Build the per-event global shared by generation and trace evaluations.

    With text projections enabled, this is the target-independent event shape exposed through
    `evaluation_events`. The trace-only `events` compatibility global disables them so saved
    source keeps its original shape and memory cost.
    """
    io = extract_event_io(event_type, properties)
    event_global: dict[str, Any] = {
        "uuid": event_uuid,
        "event": event_type,
        "timestamp": timestamp,
        "input": coerce_hog_io_value(io.input_raw),
        "output": coerce_hog_io_value(io.output_raw),
        "properties": {key: value for key, value in properties.items() if key not in HEAVY_PROPERTY_NAMES},
    }
    if include_text:
        event_global["input_text"] = _extract_hog_message_text(io.input_raw)
        event_global["output_text"] = _extract_hog_output_text(io.output_raw)
    return event_global


def execute_hog_eval_bytecode(bytecode: list, globals_dict: dict[str, Any], allows_na: bool) -> dict[str, Any]:
    """Run compiled Hog eval bytecode against pre-built globals and shape the verdict.

    Shared by the single-event and trace-level Hog activities — only the globals differ.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}, plus "applicable"
    when allows_na and a `return null` is treated as N/A, "user_input_error": True when this unit's
    data defeated the user's Hog source, and "unexpected": True when the failure was a bug in our
    code rather than in the user's Hog source or its input.
    """
    try:
        response = execute_bytecode(
            bytecode,
            globals=globals_dict,
            timeout=timedelta(seconds=10),
            team=None,
        )
    except HogVMRuntimeExceededException:
        return {"verdict": None, "reasoning": "", "error": "Execution timed out (10s limit exceeded)"}
    except HogVMMemoryExceededException:
        return {"verdict": None, "reasoning": "", "error": "Memory limit exceeded"}
    except HogVMException as e:
        return {"verdict": None, "reasoning": "", "error": f"Runtime error: {e}"}
    except HOG_INPUT_ERROR_TYPES as e:
        return {
            "verdict": None,
            "reasoning": "",
            "error": f"{type(e).__name__}: {e}",
            "user_input_error": True,
        }
    except Exception as e:
        logger.exception("Unexpected error executing Hog eval bytecode")
        return {
            "verdict": None,
            "reasoning": "",
            "error": f"Unexpected error during evaluation: {type(e).__name__}: {e}",
            "unexpected": True,
        }

    reasoning = "\n".join(response.stdout) if response.stdout else ""

    if response.result is None and allows_na:
        return {"verdict": None, "applicable": False, "reasoning": reasoning, "error": None}

    if not isinstance(response.result, bool):
        hint = " (or null if N/A is enabled)" if allows_na else ""
        return {
            "verdict": None,
            "reasoning": reasoning,
            "error": f"Must return boolean{hint}, got {type(response.result).__name__}: {response.result}",
        }

    result: dict[str, Any] = {"verdict": response.result, "reasoning": reasoning, "error": None}
    if allows_na:
        result["applicable"] = True
    return result


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
            input_error_spec = require_user_error_spec("hog_input_error")
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
            skipped_result: EvaluationActivityResult = {
                "result_type": "boolean",
                "verdict": None if allows_na else False,
                # Leads with the safe message: `detail` is a Python exception repr, which is not a
                # Hog concept, and `reasoning` is the only text the run shows the user.
                "reasoning": f"{input_error_spec.safe_message} ({detail})" if detail else input_error_spec.safe_message,
                "allows_na": allows_na,
                "skipped": True,
                "skip_reason": input_error_spec.error_type,
            }
            if allows_na:
                skipped_result["applicable"] = False
            return skipped_result

        # The user's Hog source itself errored — an expected outcome of running customer-authored
        # code, recorded as a skipped evaluation rather than raised (which would flood error
        # tracking with one event per unit). Marked terminal so the workflow disables the broken
        # eval instead of re-running it against every matching unit (mirrors the generation path).
        spec = require_user_error_spec("hog_error")
        error_detail = status_reason_detail_for_terminal_user_error(spec, result["error"]) or spec.safe_message
        errored_result: EvaluationActivityResult = {
            "result_type": "boolean",
            "verdict": None if allows_na else False,
            "reasoning": error_detail,
            "allows_na": allows_na,
            "skipped": True,
            "skip_reason": "hog_error",
            "terminal_user_error": True,
            "status_reason": spec.status_reason,
        }
        if allows_na:
            errored_result["applicable"] = False
        return errored_result

    activity_result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": result["verdict"],
        "reasoning": result["reasoning"],
        "allows_na": allows_na,
    }
    if allows_na:
        activity_result["applicable"] = result.get("applicable", True)
    return activity_result


def run_hog_eval(bytecode: list, event_data: dict[str, Any], allows_na: bool = False) -> dict[str, Any]:
    """Run compiled Hog bytecode against a single event.

    Used by both the Temporal activity and the test endpoint.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}.
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

    return execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=allows_na)


@temporalio.activity.defn
async def execute_hog_eval_activity(evaluation: dict[str, Any], event_data: dict[str, Any]) -> EvaluationActivityResult:
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
        return run_hog_eval(bytecode, event_data, allows_na=allows_na)

    result = await database_sync_to_async(_execute, thread_sensitive=False)()

    return finalize_hog_eval_result(result, evaluation=evaluation, allows_na=allows_na, unit_label=None)

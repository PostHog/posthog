import json
from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_errors import (
    require_user_error_spec,
    status_reason_detail_for_terminal_user_error,
)
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.utils import HogVMException, HogVMMemoryExceededException, HogVMRuntimeExceededException

logger = structlog.get_logger(__name__)


def coerce_hog_io_value(value: Any) -> str:
    """Coerce an extracted input/output value into a string for Hog globals.

    String operations (ilike, length, etc.) should work consistently; users can still
    parse structured data with jsonParse() when needed.
    """
    if isinstance(value, list | dict):
        return json.dumps(value)
    return "" if value is None or value == "" else str(value)


def execute_hog_eval_bytecode(bytecode: list, globals_dict: dict[str, Any], allows_na: bool) -> dict[str, Any]:
    """Run compiled Hog eval bytecode against pre-built globals and shape the verdict.

    Shared by the single-event and trace-level Hog activities — only the globals differ.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}, plus "applicable"
    when allows_na and a `return null` is treated as N/A, and "unexpected": True when the failure
    was a bug in our code rather than in the user's Hog source.
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


def run_hog_eval(bytecode: list, event_data: dict[str, Any], allows_na: bool = False) -> dict[str, Any]:
    """Run compiled Hog bytecode against a single event.

    Used by both the Temporal activity and the test endpoint.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}.
    When allows_na=True, a `return null` is treated as N/A (not an error).
    Sets "unexpected": True only when the bytecode raised something other than a
    HogVM error — i.e. a bug in our code rather than in the user's Hog source.
    """
    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    event_type = event_data["event"]
    input_raw, output_raw = extract_event_io(event_type, properties)

    globals_dict: dict[str, Any] = {
        "input": coerce_hog_io_value(input_raw),
        "output": coerce_hog_io_value(output_raw),
        "properties": properties,
        "event": {
            "uuid": event_data.get("uuid", ""),
            "event": event_type,
            "distinct_id": event_data.get("distinct_id", ""),
        },
    }

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

    if result["error"]:
        if result.get("unexpected"):
            # A genuine bug in our evaluation code (not the user's Hog). Raise so the Temporal
            # interceptor reports it to error tracking and we get paged to investigate.
            raise ApplicationError(
                f"Hog evaluation error: {result['error']}",
                non_retryable=True,
            )

        # The user's Hog source itself errored (invalid code, execution timeout, or a
        # non-boolean result). That's an expected outcome of running customer-authored code,
        # not a system fault — record it as a skipped evaluation the user can see, rather than
        # raising (which would flood error tracking with one event per matching generation).
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

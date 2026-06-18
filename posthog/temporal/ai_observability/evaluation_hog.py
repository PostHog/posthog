import json
from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.utils import HogVMException, HogVMMemoryExceededException, HogVMRuntimeExceededException

logger = structlog.get_logger(__name__)


def run_hog_eval(bytecode: list, event_data: dict[str, Any], allows_na: bool = False) -> dict[str, Any]:
    """Run compiled Hog bytecode against a single event.

    Used by both the Temporal activity and the test endpoint.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}.
    When allows_na=True, a `return null` is treated as N/A (not an error).
    """
    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    event_type = event_data["event"]
    input_raw, output_raw = extract_event_io(event_type, properties)

    input_val = json.dumps(input_raw) if isinstance(input_raw, list | dict) else (input_raw or "")
    output_val = json.dumps(output_raw) if isinstance(output_raw, list | dict) else (output_raw or "")

    globals_dict: dict[str, Any] = {
        "input": input_val,
        "output": output_val,
        "properties": properties,
        "event": {
            "uuid": event_data.get("uuid", ""),
            "event": event_type,
            "distinct_id": event_data.get("distinct_id", ""),
        },
    }

    try:
        response = execute_bytecode(
            bytecode,
            globals=globals_dict,
            timeout=timedelta(seconds=5),
            team=None,
        )
    except HogVMRuntimeExceededException:
        return {"verdict": None, "reasoning": "", "error": "Execution timed out (5s limit exceeded)"}
    except HogVMMemoryExceededException:
        return {"verdict": None, "reasoning": "", "error": "Memory limit exceeded"}
    except HogVMException as e:
        return {"verdict": None, "reasoning": "", "error": f"Runtime error: {e}"}
    except Exception:
        logger.exception("Unexpected error executing Hog eval bytecode")
        return {"verdict": None, "reasoning": "", "error": "Unexpected error during evaluation"}

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
        raise ApplicationError(
            f"Hog evaluation error: {result['error']}",
            non_retryable=True,
        )

    activity_result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": result["verdict"],
        "reasoning": result["reasoning"],
        "allows_na": allows_na,
    }
    if allows_na:
        activity_result["applicable"] = result.get("applicable", True)

    return activity_result

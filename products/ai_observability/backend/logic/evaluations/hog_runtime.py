import json
from datetime import timedelta
from typing import Any

import structlog

from posthog.schema import LLMTrace

from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES

from products.ai_observability.backend.logic.evaluations.event_io import extract_event_io
from products.ai_observability.backend.logic.message_utils import extract_text_from_messages
from products.ai_observability.backend.models.evaluation_configs import (
    CategoricalOutputConfig,
    InvalidEvaluationCategories,
    NumericOutputConfig,
    NumericScoreOutOfBounds,
)

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
#   returns null past the end of an array), and the VM rejects a wrong-arity builtin at the dispatch
#   site, so a source like `jsonParse()` raises HogVMException without reaching the STL function.
#   Such a source fails on every unit, and `finalize_hog_eval_result` makes that a terminal
#   hog_error which disables the evaluation. Neither error may count as an input error, or the
#   broken source would skip every unit silently and blame the customer's data.
#
# The VM does raise IndexError for one source shape: a `throw` after a function returned from
# inside `try`. The VM keeps the returned frame's handler and jumps into a frame that no longer
# exists. `execute_hog_eval_bytecode` treats that IndexError as a broken source, like HogVMException.
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


# The VM keeps printed lines outside its memory accounting, so a print in a loop could fill a worker's memory
# within the time limit. Output past this many characters is dropped.
MAX_HOG_OUTPUT_CHARS = 64_000


class _BoundedOutput(list[str]):
    """The VM's stdout list for one run. Every print, direct or through an alias, appends here."""

    def __init__(self) -> None:
        super().__init__()
        self.chars = 0

    def append(self, line: str) -> None:
        if self.chars >= MAX_HOG_OUTPUT_CHARS:
            return
        line = line[: MAX_HOG_OUTPUT_CHARS - self.chars]
        super().append(line)
        # The newline that joins the lines counts too, so empty prints also use up the cap.
        self.chars += len(line) + 1


def execute_hog_eval_bytecode(
    bytecode: list,
    globals_dict: dict[str, Any],
    allows_na: bool,
    *,
    output_type: str = "boolean",
    output_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run compiled Hog eval bytecode against pre-built globals and shape the output.

    Shared by the single-event and trace-level Hog activities — only the globals differ.
    Returns {"verdict": bool | None, "reasoning": str, "error": str | None}, plus "applicable"
    when allows_na and a `return null` is treated as N/A, "user_input_error": True when this unit's
    data defeated the user's Hog source, and "unexpected": True when the failure was a bug in our
    code rather than in the user's Hog source or its input.
    Numeric success replaces `verdict` with a validated `score`.
    """
    output = _BoundedOutput()
    try:
        response = execute_bytecode(
            bytecode,
            globals=globals_dict,
            stdout=output,
            timeout=timedelta(seconds=10),
            team=None,
        )
    except HogVMRuntimeExceededException:
        return {"verdict": None, "reasoning": "", "error": "Execution timed out (10s limit exceeded)"}
    except HogVMMemoryExceededException:
        return {"verdict": None, "reasoning": "", "error": "Memory limit exceeded"}
    except HogVMException as e:
        return {"verdict": None, "reasoning": "", "error": f"Runtime error: {e}"}
    except IndexError as e:
        return {"verdict": None, "reasoning": "", "error": f"Runtime error: {type(e).__name__}: {e}"}
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

    reasoning = "\n".join(output)

    if response.result is None and allows_na:
        return {"verdict": None, "applicable": False, "reasoning": reasoning, "error": None}

    if output_type == "categorical":
        try:
            categories = CategoricalOutputConfig.model_validate(output_config or {}).validate_result(response.result)
        except InvalidEvaluationCategories as error:
            return {"verdict": None, "reasoning": reasoning, "error": str(error), "user_input_error": True}
        except ValueError as error:
            return {"verdict": None, "reasoning": reasoning, "error": str(error)}
        return {"categories": categories, "reasoning": reasoning, "error": None, "applicable": True}

    if output_type == "numeric":
        try:
            score = NumericOutputConfig.model_validate(output_config or {}).validate_score(response.result)
        except NumericScoreOutOfBounds as error:
            return {
                "verdict": None,
                "reasoning": reasoning,
                "error": str(error),
                "user_input_error": True,
                "skip_reason": "score_out_of_bounds",
            }
        except ValueError as error:
            return {"verdict": None, "reasoning": reasoning, "error": str(error)}
        numeric_result: dict[str, Any] = {"score": score, "reasoning": reasoning, "error": None}
        if allows_na:
            numeric_result["applicable"] = True
        return numeric_result

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


def build_trace_hog_globals(trace: LLMTrace, trace_id: str, *, bytecode: list[Any] | None = None) -> dict[str, Any]:
    """Build Hog globals for a trace-level eval.

    `events` and `trace` keep their original shapes for saved trace Hog source. New target-independent
    source uses `evaluation_events`, which adds readable text projections, and `target`.

    Existing bytecode receives the original globals. Bytecode that uses a new shared global only
    builds the event collections it references, avoiding duplicate HogVM and worker memory cost.
    """
    trace_events = trace.events or []
    references_target = bytecode is not None and hog_bytecode_references_global(bytecode, "target")
    references_events = bytecode is not None and hog_bytecode_references_global(bytecode, "events")
    references_evaluation_events = bytecode is not None and hog_bytecode_references_global(
        bytecode, "evaluation_events"
    )
    can_skip_compatibility_events = (references_target or references_evaluation_events) and not references_events
    globals_dict: dict[str, Any] = {
        "trace": {"id": trace_id, "event_count": len(trace_events)},
    }
    if bytecode is None or references_target:
        globals_dict["target"] = {
            "type": "trace",
            "id": trace_id,
            "total_cost_usd": trace.totalCost,
            "total_latency_seconds": trace.totalLatency,
        }
    if bytecode is None or not can_skip_compatibility_events:
        globals_dict["events"] = [
            build_hog_event_global(
                event.event,
                event.properties,
                event_uuid=event.id,
                timestamp=event.createdAt,
                include_text=False,
            )
            for event in trace_events
        ]
    if bytecode is None or references_evaluation_events:
        globals_dict["evaluation_events"] = [
            build_hog_event_global(
                event.event,
                event.properties,
                event_uuid=event.id,
                timestamp=event.createdAt,
            )
            for event in trace_events
        ]
    return globals_dict

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
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult, build_skipped_evaluation_result
from posthog.temporal.ai_observability.message_utils import extract_text_from_messages
from posthog.temporal.ai_observability.metrics import increment_user_errors

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


# The reply-only text below decides by where the output came from, not by what it looks like.
# `$ai_output_choices` holds provider messages: take the text out of known message and block shapes,
# drop the SDK items that are known not to be the reply, and keep anything else whole, because a
# structured output is the reply itself. `$ai_output` and `$ai_output_state` hold the app's own
# output, which is the reply as written. Captured output is user data, so a `type` or `role` can be
# any JSON value, and only plain strings count as discriminators.
_TEXT_BLOCK_TYPES = frozenset({"text", "output_text"})
# Content block types an SDK can record as flat output without a message wrapper. Only the text
# types carry reply text; the rest are reasoning, tool use, or media.
_CONTENT_BLOCK_TYPES = _TEXT_BLOCK_TYPES | frozenset(
    {
        "thinking",
        "redacted_thinking",
        "tool_use",
        "server_tool_use",
        "tool_result",
        "web_search_tool_result",
        "image",
        "refusal",
    }
)
# OTel follow-up messages that carry reasoning or tool results.
_NON_REPLY_ROLES = frozenset({"thinking", "tool"})
_MESSAGE_KEYS = ("content", "refusal", "text", "tool_calls")


def _str_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _is_non_reply_item(item: dict[str, Any]) -> bool:
    """A Responses or SDK item that holds reasoning, a tool call, or a tool result rather than reply text."""
    item_type = _str_value(item.get("type"))
    return item_type is not None and (item_type == "reasoning" or item_type.endswith(("_call", "_call_output")))


def _is_message(choice: dict[str, Any]) -> bool:
    """Whether a dict is a provider message envelope rather than a structured-output payload."""
    if _str_value(choice.get("role")) is not None:
        return True
    # A role-less legacy choice such as `{"text": ...}` or `{"content": ...}`. A dict with its own
    # string `type` and no role, such as `{"type": "invoice", ...}`, is a payload instead.
    return any(key in choice for key in _MESSAGE_KEYS) and _str_value(choice.get("type")) is None


def _scalar_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None


def _block_text(block: Any) -> str | None:
    """The reply text in one content block, or None for a block that is not reply text."""
    text = _scalar_text(block)
    if text is not None or not isinstance(block, dict):
        return text
    block_type = block.get("type", "text")
    if not isinstance(block_type, str):
        return json.dumps(block, default=str)
    if block_type == "refusal":
        # Counted as reply text, as a refusal on the message itself is.
        return _scalar_text(block.get("refusal"))
    # Gemini marks its reasoning as a text part with `thought` set.
    if block_type not in _TEXT_BLOCK_TYPES or block.get("thought"):
        return None
    return _scalar_text(block.get("text", block.get("content")))


def _reply_text_from_content(content: Any) -> str:
    text = _scalar_text(content)
    if text is not None:
        return text
    if isinstance(content, dict):
        text = _block_text(content)
        # A content dict that is not a text block, such as a parsed object, is the reply itself.
        return text if text is not None else json.dumps(content, default=str)
    if isinstance(content, list):
        return " ".join(text for text in (_block_text(block) for block in content) if text)
    return ""


def _is_flat_block(item: dict[str, Any]) -> bool:
    """A content block recorded without a message around it, matched on its fields as well as its `type`."""
    item_type = _str_value(item.get("type"))
    if item_type in _TEXT_BLOCK_TYPES:
        return "text" in item or "content" in item
    if item_type == "refusal":
        return "refusal" in item
    return item_type in _CONTENT_BLOCK_TYPES


def _decode_choice_string(choice: str) -> Any:
    try:
        decoded = json.loads(choice)
    except (ValueError, TypeError):
        return choice
    is_message = isinstance(decoded, dict) and (
        isinstance(decoded.get("message"), dict) or _str_value(decoded.get("role")) is not None
    )
    return decoded if is_message else choice


def _reply_text_from_choices(output: Any) -> str:
    if isinstance(output, dict) and isinstance(output.get("choices"), list):
        output = output["choices"]

    replies: list[str] = []
    for choice in output if isinstance(output, list) else [output]:
        if isinstance(choice, str):
            choice = _decode_choice_string(choice)
        if not isinstance(choice, dict):
            text = _scalar_text(choice)
            replies.append(text if text is not None else coerce_hog_io_value(choice))
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            choice = message
        if _str_value(choice.get("role")) in _NON_REPLY_ROLES or _is_non_reply_item(choice):
            continue
        if _str_value(choice.get("role")) is None and _is_flat_block(choice):
            replies.append(_block_text(choice) or "")
        elif not _is_message(choice):
            replies.append(json.dumps(choice, default=str))
        elif isinstance(choice.get("parts"), list):
            # OTel keeps text parts next to reasoning and tool-call parts, with the text under `content`.
            replies.append(
                " ".join(
                    text
                    for part in choice["parts"]
                    if isinstance(part, dict) and part.get("type") == "text"
                    for text in [_scalar_text(part.get("content"))]
                    if text
                )
            )
        else:
            replies.append(_reply_text_from_content(_get_hog_output_choice_content(choice)))
    return "\n".join(reply for reply in replies if reply.strip())


def _extract_hog_reply_text(output: Any, *, from_choices: bool) -> str:
    """The text of the model's reply alone, without reasoning, tool calls, tool results, or role labels.

    `output_text` keeps all of those because LLM judges read it as a conversation. Checks on the
    reply itself, such as "is this valid JSON" or "is it empty", need the reply on its own.
    """
    if from_choices:
        if isinstance(output, str):
            # Some SDKs send the choices as one JSON string.
            try:
                output = json.loads(output)
            except (ValueError, TypeError):
                return output
        return _reply_text_from_choices(output)
    # The app's own output is the reply as written, unless it is one assistant message.
    if isinstance(output, dict) and output.get("role") == "assistant":
        return _reply_text_from_choices([output])
    text = _scalar_text(output)
    return text if text is not None else coerce_hog_io_value(output)


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
        # Mirrors `extract_event_io`, which reads `$ai_output_choices` first on a generation.
        from_choices = event_type == "$ai_generation" and bool(properties.get("$ai_output_choices"))
        event_global["reply_text"] = _extract_hog_reply_text(io.output_raw, from_choices=from_choices)
    return event_global


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

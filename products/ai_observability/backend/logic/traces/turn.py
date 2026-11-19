import json
from collections.abc import Callable, Sequence
from typing import Final, Self

from posthog.dataclasses import frozen

from ...facade import contracts
from ..message_normalizer.values import Value
from .step_content import SideReading, StepReading

TURN_INPUT_TAIL: Final = 4
PREVIEW_MAX_CHARS: Final = 200


@frozen
class Unreadable:
    reason: contracts.TracePreviewMissingReason


TOO_LARGE: Final = Unreadable(reason=contracts.TracePreviewMissingReason.TOO_LARGE)
TIMED_OUT: Final = Unreadable(reason=contracts.TracePreviewMissingReason.TIMED_OUT)


@frozen
class Side[T]:
    """What could be read of one side of a step, and why the rest of it could not be."""

    value: T
    unread: Unreadable | None


# A step side whose value is None failed to read.
type StepSide = Side[contracts.TraceSideContent | None]
type TurnSide = str | Unreadable | None


@frozen
class TurnStep:
    input: StepSide
    output: StepSide

    @classmethod
    def of(
        cls,
        reading: StepReading,
        *,
        input_unread: Unreadable | None,
        output_unread: Unreadable | None,
        out_of_time: bool,
    ) -> Self:
        """`out_of_time` says the page's time ran out by the end of the read, so a side that failed timed out."""
        return cls(
            input=_side(reading.content.input, reading.input, input_unread, out_of_time),
            output=_side(reading.content.output, reading.output, output_unread, out_of_time),
        )


@frozen
class Turn:
    message: TurnSide
    answer: TurnSide

    @classmethod
    def of(
        cls, *, state: TurnStep | None, first_generation: TurnStep | None, latest_generation: TurnStep | None
    ) -> "Turn":
        state_input = state.input if state else None
        state_output = state.output if state else None
        first_input = first_generation.input if first_generation else None
        latest_output = latest_generation.output if latest_generation else None
        return cls(
            message=_text_or_why(
                (state_input, first_input),
                _message_of(_content(state_input)),
                _message_of(_content(first_input)),
                _json_text(_content(state_input)),
            ),
            answer=_text_or_why(
                (state_output, latest_output),
                _answer_of(_content(state_output)),
                _answer_of(_content(latest_output)),
                _json_text(_content(state_output)),
            ),
        )


@frozen
class TurnSides:
    input: StepSide
    output: StepSide

    @classmethod
    def of(
        cls,
        *,
        state: TurnStep | None,
        first_generation: TurnStep | None,
        latest_generation_input: StepSide | None,
        latest_generation: TurnStep | None,
    ) -> Self:
        """The input and output a turn shows: what its trace added, not the history every generation carries."""
        output_source = latest_generation or first_generation
        return cls(
            input=_conversation_or(
                state.input if state else None,
                lambda: _added_input(first_generation.input if first_generation else None, latest_generation_input),
            ),
            output=_conversation_or(
                state.output if state else None,
                lambda: output_source.output if output_source else _NOTHING_READ,
            ),
        )


def readable_tail(items: Sequence[Value], over_caps: Sequence[bool]) -> Side[Value]:
    """The items after the last one over the size cap, flagged by the matching entry of `over_caps`.

    An item that could not be read may be the latest user message, and its role is unknown before normalizing, so no
    item older than it can stand for the latest message."""
    last_over_cap = next((index for index in reversed(range(len(over_caps))) if over_caps[index]), None)
    if last_over_cap is None:
        return Side(value=items, unread=None)
    return Side(value=items[last_over_cap + 1 :], unread=TOO_LARGE)


def preview(side: TurnSide, limit: int = PREVIEW_MAX_CHARS) -> str | None:
    if not isinstance(side, str):
        return None
    collapsed = " ".join(side.split())[:limit]
    return collapsed or None


def missing_reason(side: TurnSide) -> contracts.TracePreviewMissingReason | None:
    return side.reason if isinstance(side, Unreadable) else None


_NOTHING_READ: Final[StepSide] = Side(value=None, unread=None)


def _conversation_or(state_side: StepSide | None, fallback: Callable[[], StepSide]) -> StepSide:
    if (
        state_side is not None
        and isinstance(state_side.value, contracts.TraceMessagesSide)
        and state_side.value.messages
    ):
        return state_side
    return fallback()


def _added_input(first: StepSide | None, latest: StepSide | None) -> StepSide:
    if first is None:
        return latest or _NOTHING_READ
    if not isinstance(first.value, contracts.TraceMessagesSide):
        return first
    anchor = _anchor(first.value.messages)
    if not anchor:
        return first
    if latest is not None and isinstance(latest.value, contracts.TraceMessagesSide):
        start = _last_run_start(latest.value.messages, anchor)
        if start is not None:
            after = latest.value.messages[start + len(anchor) :]
            return Side(value=_messages([*anchor, *after]), unread=latest.unread or first.unread)
    return Side(value=_messages(anchor), unread=first.unread)


def _messages(messages: list[contracts.TraceMessage]) -> contracts.TraceMessagesSide:
    return contracts.TraceMessagesSide(kind="messages", messages=messages)


def _anchor(messages: list[contracts.TraceMessage]) -> list[contracts.TraceMessage]:
    """The first user message after the last assistant message, and everything after it.

    With no user message after the last assistant message (a trace that starts mid agent loop, or an assistant
    prefill), the last user message and everything after it."""
    after_assistant = next((i + 1 for i in reversed(range(len(messages))) if messages[i].role == "assistant"), 0)
    first_user = next((i for i in range(after_assistant, len(messages)) if messages[i].role == "user"), None)
    if first_user is None:
        first_user = next((i for i in reversed(range(len(messages))) if messages[i].role == "user"), None)
    return [] if first_user is None else messages[first_user:]


def _last_run_start(messages: list[contracts.TraceMessage], run: list[contracts.TraceMessage]) -> int | None:
    """Where `run` last appears in `messages`, comparing role and parts, since ids differ between generations."""
    return next(
        (
            start
            for start in reversed(range(len(messages) - len(run) + 1))
            if all(_same_message(messages[start + offset], message) for offset, message in enumerate(run))
        ),
        None,
    )


def _same_message(a: contracts.TraceMessage, b: contracts.TraceMessage) -> bool:
    return a.role == b.role and a.parts == b.parts


def _side(
    content: contracts.TraceSideContent, reading: SideReading, unread: Unreadable | None, out_of_time: bool
) -> StepSide:
    if reading.runtime_error:
        return Side(value=None, unread=unread or (TIMED_OUT if out_of_time else None))
    return Side(value=content, unread=unread)


def _content(side: StepSide | None) -> contracts.TraceSideContent | None:
    return side.value if side else None


def _text_or_why(sides: Sequence[StepSide | None], *texts: str | None) -> TurnSide:
    text = next((text for text in texts if text is not None), None)
    if text is not None:
        return text
    return next((side.unread for side in sides if side is not None and side.unread is not None), None)


def _nonblank(text: str) -> str | None:
    return text if text.strip() else None


def _json_text(side: contracts.TraceSideContent | None) -> str | None:
    if not isinstance(side, contracts.TraceJsonSide) or side.value is None:
        return None
    return _nonblank(_as_text(side.value))


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _message_of(side: contracts.TraceSideContent | None) -> str | None:
    if not isinstance(side, contracts.TraceMessagesSide):
        return None
    tail = side.messages[-TURN_INPUT_TAIL:]
    chosen = _last_with_text([m for m in tail if m.role == "user"]) or _last_with_content(
        [m for m in tail if m.role != "system"]
    )
    return _content_of(chosen) if chosen else None


def _answer_of(side: contracts.TraceSideContent | None) -> str | None:
    if not isinstance(side, contracts.TraceMessagesSide):
        return None
    assistant = [m for m in side.messages if m.role == "assistant"]
    chosen = (
        _last_with_text(assistant)
        or _last_with_content([m for m in assistant if _tool_calls(m)])
        or _last_with_content(side.messages)
    )
    return _content_of(chosen) if chosen else None


def _texts(message: contracts.TraceMessage) -> list[str]:
    return [part.text for part in message.parts if isinstance(part, contracts.TraceTextPart) and part.text.strip()]


def _tool_calls(message: contracts.TraceMessage) -> list[contracts.TraceToolCallPart]:
    return [part for part in message.parts if isinstance(part, contracts.TraceToolCallPart)]


def _last_with_text(messages: list[contracts.TraceMessage]) -> contracts.TraceMessage | None:
    return next((m for m in reversed(messages) if _texts(m)), None)


def _last_with_content(messages: list[contracts.TraceMessage]) -> contracts.TraceMessage | None:
    return next((m for m in reversed(messages) if _texts(m) or _tool_calls(m)), None)


def _content_of(message: contracts.TraceMessage) -> str | None:
    texts = _texts(message)
    if texts:
        return "\n".join(texts)
    return _nonblank(_render_call(_tool_calls(message)[0]))


def _render_call(call: contracts.TraceToolCallPart) -> str:
    return f"{call.name} {_as_text(call.args)[:PREVIEW_MAX_CHARS]}".strip()

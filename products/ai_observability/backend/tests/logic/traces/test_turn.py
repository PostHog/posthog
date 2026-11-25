from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.message_normalizer.values import Value
from products.ai_observability.backend.logic.traces.step_content import SideReading, StepReading
from products.ai_observability.backend.logic.traces.turn import (
    PREVIEW_MAX_CHARS,
    TIMED_OUT,
    TOO_LARGE,
    Side,
    Turn,
    TurnStep,
    Unreadable,
    missing_reason,
    preview,
    readable_tail,
)

OK = SideReading(recognized=True)
FAILED = SideReading(recognized=False, runtime_error="boom")


def text_message(role: contracts.TraceMessageRole, text: str) -> contracts.TraceMessage:
    return contracts.TraceMessage(
        id=f"m-{role}-{text}",
        role=role,
        parts=[contracts.TraceTextPart(kind="text", text=text)],
        is_internal=role == "tool",
        source_node_id=None,
    )


def parts_message(role: contracts.TraceMessageRole, *parts: contracts.TraceMessagePart) -> contracts.TraceMessage:
    return contracts.TraceMessage(
        id=f"m-{role}-{len(parts)}", role=role, parts=list(parts), is_internal=True, source_node_id=None
    )


def conversation(*messages: contracts.TraceMessage) -> contracts.TraceMessagesSide:
    return contracts.TraceMessagesSide(kind="messages", messages=list(messages))


def json_side(value: object) -> contracts.TraceJsonSide:
    return contracts.TraceJsonSide(kind="json", value=value)


def reading(
    input: contracts.TraceMessagesSide | contracts.TraceJsonSide | None = None,
    output: contracts.TraceMessagesSide | contracts.TraceJsonSide | None = None,
    *,
    input_reading: SideReading = OK,
    output_reading: SideReading = OK,
    input_unread: Unreadable | None = None,
    output_unread: Unreadable | None = None,
    out_of_time: bool = False,
) -> TurnStep:
    return TurnStep.of(
        StepReading(
            content=contracts.TraceNodeContent(
                input=input if input is not None else conversation(),
                output=output if output is not None else conversation(),
            ),
            input=input_reading,
            output=output_reading,
        ),
        input_unread=input_unread,
        output_unread=output_unread,
        out_of_time=out_of_time,
    )


SEARCH_CALL = contracts.TraceToolCallPart(kind="toolCall", name="search", args={"q": "refund policy"}, result=None)
LONG_SEARCH_CALL = contracts.TraceToolCallPart(kind="toolCall", name="search", args={"q": "x" * 300}, result=None)
THINKING = contracts.TraceThinkingPart(kind="thinking", text="let me think")
IMAGE = contracts.TraceAttachmentPart(
    kind="attachment", media_type="image", name=None, mime_type="image/png", url="https://example.com/photo.png"
)
SYSTEM_PROMPT = text_message("system", "You are a helpful assistant.")


@parameterized.expand(
    [
        (
            "state conversation wins over the generation",
            reading(input=conversation(text_message("user", "from state"))),
            reading(input=conversation(text_message("user", "from generation"))),
            "from state",
        ),
        (
            "state json falls through to the generation",
            reading(input=json_side({"a": 1})),
            reading(input=conversation(text_message("user", "from generation"))),
            "from generation",
        ),
        (
            "a user message outside the tail is not picked",
            None,
            reading(
                input=conversation(
                    text_message("user", "too early"),
                    text_message("assistant", "a1"),
                    text_message("assistant", "a2"),
                    text_message("assistant", "a3"),
                    text_message("assistant", "a4"),
                )
            ),
            None,
        ),
        (
            "last user message among the tail",
            None,
            reading(
                input=conversation(
                    text_message("user", "first"),
                    text_message("assistant", "a1"),
                    text_message("user", "second"),
                    text_message("assistant", "a2"),
                )
            ),
            "second",
        ),
        (
            "a tail of assistant and tool messages gives no input",
            None,
            reading(
                input=conversation(
                    text_message("system", "rules"),
                    parts_message("assistant", SEARCH_CALL),
                    text_message("tool", "refunds take five days"),
                    text_message("assistant", "Let me check."),
                )
            ),
            None,
        ),
        ("a system message alone is never the input", None, reading(input=conversation(SYSTEM_PROMPT)), None),
        (
            "a system message is never the input when the user's message has no text",
            None,
            reading(input=conversation(SYSTEM_PROMPT, parts_message("user", IMAGE))),
            None,
        ),
        (
            "a user message after the system message is the input",
            None,
            reading(input=conversation(SYSTEM_PROMPT, text_message("user", "What is in this picture?"))),
            "What is in this picture?",
        ),
        (
            "generation gives nothing and a json state gives compact json",
            reading(input=json_side({"query": "naïve café", "n": 1})),
            reading(),
            '{"query":"naïve café","n":1}',
        ),
        ("a json string state is used as is", reading(input=json_side("plain text")), None, "plain text"),
        (
            "a whitespace-only user message falls through to the earlier one",
            None,
            reading(input=conversation(text_message("user", "earlier"), text_message("user", " \n "))),
            "earlier",
        ),
        (
            "an empty state conversation falls through to the generation",
            reading(input=conversation()),
            reading(input=conversation(text_message("user", "from generation"))),
            "from generation",
        ),
        (
            "a failed state side gives nothing even with a json value",
            reading(input=json_side({"a": 1}), input_reading=FAILED),
            None,
            None,
        ),
        (
            "a failed state side when the page is out of time timed out",
            reading(input=json_side({"a": 1}), input_reading=FAILED, out_of_time=True),
            None,
            TIMED_OUT,
        ),
        ("an oversized latest input item gives its reason", None, reading(input_unread=TOO_LARGE), TOO_LARGE),
        (
            "an oversized item cut from the tail before an image-only message gives its reason",
            None,
            reading(input=conversation(parts_message("user", IMAGE)), input_unread=TOO_LARGE),
            TOO_LARGE,
        ),
        (
            "an oversized item cut from the tail before a system message gives its reason",
            None,
            reading(input=conversation(SYSTEM_PROMPT), input_unread=TOO_LARGE),
            TOO_LARGE,
        ),
        (
            "an oversized item cut from the tail before a user message gives that message",
            None,
            reading(input=conversation(text_message("user", "newer")), input_unread=TOO_LARGE),
            "newer",
        ),
        (
            "a blank json state is no text, so the generation's reason shows",
            reading(input=json_side(" \n ")),
            reading(input_unread=TOO_LARGE),
            TOO_LARGE,
        ),
        (
            "an oversized state falls through to the generation's message",
            reading(input_unread=TOO_LARGE),
            reading(input=conversation(text_message("user", "from generation"))),
            "from generation",
        ),
        (
            "an oversized state with nothing in the generation gives its reason",
            reading(input_unread=TOO_LARGE),
            reading(),
            TOO_LARGE,
        ),
        ("nothing at all", None, None, None),
    ]
)
def test_message(
    _name: str, state: TurnStep | None, first_generation: TurnStep | None, expected: str | Unreadable | None
) -> None:
    turn = Turn.of(state=state, first_generation=first_generation, latest_generation=None)

    assert turn.message == expected


@parameterized.expand(
    [
        (
            "last assistant text wins over a later tool result",
            None,
            reading(output=conversation(text_message("assistant", "the answer"), text_message("tool", "tool output"))),
            "the answer",
        ),
        (
            "an assistant tool call alone gives the call",
            None,
            reading(output=conversation(parts_message("assistant", SEARCH_CALL))),
            'search {"q":"refund policy"}',
        ),
        (
            "long tool call arguments are cut",
            None,
            reading(output=conversation(parts_message("assistant", LONG_SEARCH_CALL))),
            "search " + ('{"q":"' + "x" * 300 + '"}')[:PREVIEW_MAX_CHARS],
        ),
        (
            "a thinking part is not the answer",
            None,
            reading(
                output=conversation(
                    text_message("assistant", "visible"), parts_message("assistant", THINKING, SEARCH_CALL)
                )
            ),
            "visible",
        ),
        (
            "thinking only gives nothing",
            None,
            reading(output=conversation(parts_message("assistant", THINKING))),
            None,
        ),
        (
            "state conversation wins over the generation",
            reading(output=conversation(text_message("assistant", "from state"))),
            reading(output=conversation(text_message("assistant", "from generation"))),
            "from state",
        ),
        (
            "no assistant message picks the last message with content",
            None,
            reading(output=conversation(text_message("user", "u"), text_message("tool", "t"))),
            "t",
        ),
        (
            "a failed output side gives nothing",
            reading(output=json_side("ignored"), output_reading=FAILED),
            None,
            None,
        ),
        ("a json state output is the fallback", reading(output=json_side({"ok": True})), None, '{"ok":true}'),
    ]
)
def test_answer(_name: str, state: TurnStep | None, latest_generation: TurnStep | None, expected: str | None) -> None:
    turn = Turn.of(state=state, first_generation=None, latest_generation=latest_generation)

    assert turn.answer == expected


def test_an_oversized_output_gives_its_reason_on_the_answer_only() -> None:
    both = reading(input=conversation(text_message("user", "Where is my parcel?")), output_unread=TOO_LARGE)

    turn = Turn.of(state=None, first_generation=both, latest_generation=both)

    assert turn == Turn(message="Where is my parcel?", answer=TOO_LARGE)


@parameterized.expand(
    [
        ("collapses whitespace", "a\n\n  b", "a b"),
        ("cuts to the limit", "x" * 250, "x" * PREVIEW_MAX_CHARS),
        ("empty", "", None),
        ("blank", " \n ", None),
        ("none", None, None),
        ("keeps non-ascii", "naïve café 日本語", "naïve café 日本語"),
    ]
)
def test_preview(_name: str, text: str | None, expected: str | None) -> None:
    assert preview(text) == expected


@parameterized.expand(
    [
        ("text has no reason", "hello", "hello", None),
        ("an unreadable side has no text and says why", TIMED_OUT, None, "timed_out"),
        ("nothing has neither", None, None, None),
    ]
)
def test_a_side_gives_its_text_or_why_it_is_missing(
    _name: str,
    side: str | Unreadable | None,
    expected_text: str | None,
    expected_reason: contracts.TracePreviewMissingReason | None,
) -> None:
    assert (preview(side), missing_reason(side)) == (expected_text, expected_reason)


@parameterized.expand(
    [
        (
            "only the items after the last oversized one",
            ["a", None, "b", "c"],
            (False, True, False, False),
            Side(value=["b", "c"], unread=TOO_LARGE),
        ),
        (
            "nothing after an oversized last item",
            ["a", "b", None],
            (False, False, True),
            Side(value=[], unread=TOO_LARGE),
        ),
        ("no oversized item keeps every item", ["a", "b"], (False, False), Side(value=["a", "b"], unread=None)),
        (
            "a null item that is not oversized is kept",
            [{"role": "user", "content": "hi"}, None],
            (False, False),
            Side(value=[{"role": "user", "content": "hi"}, None], unread=None),
        ),
    ]
)
def test_readable_tail(_name: str, items: list[Value], over_caps: tuple[bool, ...], expected: Side[Value]) -> None:
    assert readable_tail(items, over_caps) == expected

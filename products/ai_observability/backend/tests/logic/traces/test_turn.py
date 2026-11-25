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
    TurnSides,
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


def at_node(node_id: str, *messages: contracts.TraceMessage) -> contracts.TraceMessagesSide:
    return conversation(*(m.model_copy(update={"source_node_id": node_id}) for m in messages))


def messages_of(side: Side[contracts.TraceSideContent | None]) -> list[contracts.TraceMessage]:
    assert isinstance(side.value, contracts.TraceMessagesSide)
    return side.value.messages


def tool_call_message() -> contracts.TraceMessage:
    return parts_message("assistant", SEARCH_CALL)


def sides_of(
    *,
    state: TurnStep | None = None,
    first: TurnStep | None = None,
    latest_input: contracts.TraceMessagesSide | contracts.TraceJsonSide | None = None,
    latest: TurnStep | None = None,
    latest_input_unread: Unreadable | None = None,
) -> TurnSides:
    return TurnSides.of(
        state=state,
        first_generation=first,
        latest_generation_input=Side(value=latest_input, unread=latest_input_unread) if latest_input else None,
        latest_generation=latest,
    )


HISTORY = [
    SYSTEM_PROMPT,
    text_message("user", "hi"),
    text_message("assistant", "hello"),
]


def test_sides_cut_history_at_last_user_turn() -> None:
    first = reading(at_node("gen-1", *HISTORY, text_message("user", "refund?")), at_node("gen-1", tool_call_message()))

    sides = sides_of(first=first, latest=first)

    assert sides.input.value == at_node("gen-1", text_message("user", "refund?"))


def test_sides_extend_through_latest_generation_input() -> None:
    question = text_message("user", "refund?")
    first = reading(at_node("gen-1", *HISTORY, question), at_node("gen-1", tool_call_message()))
    tool_result = text_message("tool", "refunds: 30 days")
    latest_input = at_node("gen-2", *HISTORY, question, tool_call_message(), tool_result)
    latest = reading(latest_input, at_node("gen-2", text_message("assistant", "yes, within 30 days")))

    sides = sides_of(first=first, latest_input=latest_input, latest=latest)

    assert sides.input.value == conversation(
        question.model_copy(update={"source_node_id": "gen-1"}),
        tool_call_message().model_copy(update={"source_node_id": "gen-2"}),
        tool_result.model_copy(update={"source_node_id": "gen-2"}),
    )
    assert all(m.is_internal for m in messages_of(sides.input)[1:])
    assert sides.output == latest.output


def test_sides_match_the_anchor_after_repeated_earlier_messages() -> None:
    again = text_message("user", "hi")
    first = reading(at_node("gen-1", *HISTORY, again))
    latest_input = at_node("gen-2", *HISTORY, again, tool_call_message())

    sides = sides_of(first=first, latest_input=latest_input, latest=reading(latest_input))

    assert [m.role for m in messages_of(sides.input)] == ["user", "assistant"]


def test_sides_match_an_anchor_that_starts_by_repeating_itself() -> None:
    hi, refund = text_message("user", "hi"), text_message("user", "refund?")
    first = reading(at_node("gen-1", hi, hi, refund))
    latest_input = at_node("gen-2", hi, hi, hi, refund, tool_call_message())

    sides = sides_of(first=first, latest_input=latest_input, latest=reading(latest_input))

    assert [m.role for m in messages_of(sides.input)] == ["user", "user", "user", "assistant"]


def test_sides_fall_back_when_latest_does_not_share_history() -> None:
    first = reading(at_node("gen-1", *HISTORY, text_message("user", "refund?")))
    summarizer_input = at_node("gen-9", text_message("user", "summarize this"))
    latest = reading(summarizer_input, at_node("gen-9", text_message("assistant", "a summary")))

    sides = sides_of(first=first, latest_input=summarizer_input, latest=latest)

    assert sides.input.value == at_node("gen-1", text_message("user", "refund?"))
    assert sides.output == latest.output


def test_two_trailing_user_messages_both_kept() -> None:
    first = reading(at_node("gen-1", *HISTORY, text_message("user", "refund?"), text_message("user", "also exchange?")))

    sides = sides_of(first=first, latest=first)

    assert [m.parts for m in messages_of(sides.input)] == [
        text_message("user", "refund?").parts,
        text_message("user", "also exchange?").parts,
    ]


def test_input_without_user_message_is_kept_whole() -> None:
    first = reading(at_node("gen-1", SYSTEM_PROMPT, text_message("assistant", "hello")))

    assert sides_of(first=first, latest=first).input == first.input


def test_output_falls_back_to_first_generation() -> None:
    first = reading(
        at_node("gen-1", text_message("user", "refund?")), at_node("gen-1", text_message("assistant", "ok"))
    )

    assert sides_of(first=first).output == first.output


def test_state_conversation_wins_cut_to_what_the_turn_added() -> None:
    state = reading(
        conversation(*HISTORY, text_message("user", "from state")),
        conversation(text_message("assistant", "state answer")),
    )
    first = reading(at_node("gen-1", text_message("user", "refund?")))
    latest = reading(None, at_node("gen-2", text_message("assistant", "gen answer")))

    sides = sides_of(state=state, first=first, latest=latest)

    assert sides.input == Side(value=conversation(text_message("user", "from state")), unread=None)
    assert sides.output == state.output


@parameterized.expand(
    [
        ("cut far back in the first generation", [*HISTORY, text_message("user", "refund?")], None, None),
        ("cut right before the first generation's turn", [text_message("user", "refund?")], None, TOO_LARGE),
        (
            "cut far back in the latest generation",
            [*HISTORY, text_message("user", "refund?")],
            [text_message("assistant", "older"), text_message("user", "refund?"), tool_call_message()],
            None,
        ),
        (
            "cut right before the latest generation's turn",
            [*HISTORY, text_message("user", "refund?")],
            [text_message("user", "refund?"), tool_call_message()],
            TOO_LARGE,
        ),
    ]
)
def test_an_input_cut_too_large_says_so_only_when_the_cut_reaches_the_turn(
    _name: str,
    first_tail: list[contracts.TraceMessage],
    latest_tail: list[contracts.TraceMessage] | None,
    expected: Unreadable | None,
) -> None:
    first = reading(at_node("gen-1", *first_tail), input_unread=TOO_LARGE)
    latest_input = at_node("gen-2", *latest_tail) if latest_tail is not None else None

    sides = sides_of(
        first=first,
        latest_input=latest_input,
        latest=reading(latest_input) if latest_input else first,
        latest_input_unread=TOO_LARGE,
    )

    assert sides.input.unread == expected


def test_an_empty_state_side_falls_through_to_the_generation() -> None:
    state = reading(conversation(text_message("user", "from state")), conversation())
    first = reading(
        at_node("gen-1", text_message("user", "refund?")), at_node("gen-1", text_message("assistant", "gen answer"))
    )

    sides = sides_of(state=state, first=first, latest=first)

    assert sides.input == state.input
    assert sides.output == first.output


def test_json_sides_pass_through() -> None:
    first = reading(json_side({"query": "refund?"}), json_side({"answer": 1}))

    sides = sides_of(first=first, latest=first)

    assert sides.input.value == json_side({"query": "refund?"})
    assert sides.output.value == json_side({"answer": 1})


def test_unread_side_keeps_reason() -> None:
    first = reading(input_reading=FAILED, output_reading=FAILED, input_unread=TOO_LARGE, output_unread=TOO_LARGE)

    sides = sides_of(first=first, latest=first)

    assert sides.input == Side(value=None, unread=TOO_LARGE)
    assert sides.output == Side(value=None, unread=TOO_LARGE)


@parameterized.expand(
    [
        ("mid agent loop", [text_message("user", "q"), tool_call_message(), text_message("tool", "result")]),
        ("assistant prefill", [text_message("user", "q"), text_message("assistant", "{")]),
    ]
)
def test_user_message_before_the_last_assistant_message_still_anchors(
    _name: str, tail: list[contracts.TraceMessage]
) -> None:
    first = reading(
        at_node("gen-1", SYSTEM_PROMPT, text_message("user", "earlier"), text_message("assistant", "ok"), *tail)
    )

    sides = sides_of(first=first, latest=first)

    assert sides.input.value == at_node("gen-1", *tail)


def test_state_messages_input_wins_with_json_output() -> None:
    state = reading(conversation(*HISTORY, text_message("user", "from state")), json_side({"answer": 1}))
    first = reading(at_node("gen-1", text_message("user", "refund?")))
    latest = reading(None, at_node("gen-2", text_message("assistant", "gen answer")))

    sides = sides_of(state=state, first=first, latest=latest)

    assert sides.input.value == conversation(text_message("user", "from state"))
    assert sides.output == latest.output


def test_a_state_output_that_repeats_the_conversation_is_cut_to_the_answer() -> None:
    question = text_message("user", "from state")
    answer = text_message("assistant", "state answer")
    state = reading(conversation(*HISTORY, question), conversation(*HISTORY, question, tool_call_message(), answer))

    sides = sides_of(state=state)

    assert sides.output.value == conversation(tool_call_message(), answer)


@parameterized.expand(
    [
        ("a JSON value", json_side({"answer": 1}), None, json_side({"answer": 1}), None),
        ("a reason it was not read", None, TOO_LARGE, None, TOO_LARGE),
    ]
)
def test_a_state_side_stands_when_no_generation_has_anything(
    _name: str,
    value: contracts.TraceJsonSide | None,
    unread: Unreadable | None,
    expected_value: contracts.TraceJsonSide | None,
    expected_unread: Unreadable | None,
) -> None:
    state = TurnStep(input=Side(value=value, unread=unread), output=Side(value=value, unread=unread))

    sides = sides_of(state=state)

    assert sides.input == Side(value=expected_value, unread=expected_unread)
    assert sides.output == Side(value=expected_value, unread=expected_unread)


def test_steps_lost_to_a_cut_in_the_latest_generation_are_reported() -> None:
    first = reading(at_node("gen-1", *HISTORY, text_message("user", "refund?")))
    latest_input = at_node("gen-2", text_message("tool", "the end of a large result"))

    sides = sides_of(
        first=first, latest_input=latest_input, latest=reading(latest_input), latest_input_unread=TOO_LARGE
    )

    assert sides.input == Side(value=at_node("gen-1", text_message("user", "refund?")), unread=TOO_LARGE)

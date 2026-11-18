import tracemalloc
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.facade import contracts
from products.ai_observability.backend.logic.message_normalizer import (
    run_limits as run_limits_module,
    values as values_module,
)
from products.ai_observability.backend.logic.message_normalizer.errors import (
    RecipeOutputLimitError,
    RecipeRuntimeError,
    RecipeTimeoutError,
)
from products.ai_observability.backend.logic.message_normalizer.normalizer import RecipeNormalizer
from products.ai_observability.backend.logic.message_normalizer.run_limits import time_limit
from products.ai_observability.backend.logic.message_normalizer.values import CompatMessage
from products.ai_observability.backend.logic.traces.step_messages import UnrenderableValueError, to_messages

TEAM_ID = 7


def messages_from(raw: Any, default_role: str = "user", *, prefix: str = "in", node: str | None = "gen-1"):
    compat = RecipeNormalizer().normalize_messages(raw, default_role).messages
    return to_messages(compat, id_prefix=prefix, source_node_id=node, team_id=TEAM_ID)


def text(value: str) -> contracts.TraceTextPart:
    return contracts.TraceTextPart(kind="text", text=value)


def tool_call(name: str, args: Any, result: Any = None) -> contracts.TraceToolCallPart:
    return contracts.TraceToolCallPart(kind="toolCall", name=name, args=args, result=result)


def call_then_result(result_content: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"type": "function", "id": "call-1", "function": {"name": "lookup", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": result_content},
    ]


def test_keeps_roles_and_text_in_order_mapping_developer_to_system():
    messages = messages_from(
        [
            {"role": "system", "content": "Answer billing questions."},
            {"role": "developer", "content": "Follow the house style."},
            {"role": "user", "content": "Why did my invoice go up?"},
        ]
    )

    assert [(m.role, m.parts) for m in messages] == [
        ("system", [text("Answer billing questions.")]),
        ("system", [text("Follow the house style.")]),
        ("user", [text("Why did my invoice go up?")]),
    ]
    assert (messages[0].id, messages[0].source_node_id, messages[0].is_internal) == ("in-0", "gen-1", False)


def test_pairs_tool_results_with_their_calls_instead_of_repeating_them_as_messages():
    messages = messages_from(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "call-1",
                        "function": {"name": "lookup_invoice", "arguments": '{"month":"2026-08"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": '{"total_usd":180}'},
            {"role": "assistant", "content": "Two seats were added."},
        ],
        "assistant",
        prefix="out",
    )

    assert len(messages) == 2
    assert messages[0].parts == [tool_call("lookup_invoice", {"month": "2026-08"}, {"total_usd": 180})]
    assert messages[0].is_internal is True
    assert (messages[1].role, messages[1].is_internal) == ("assistant", False)


@parameterized.expand(
    [
        ("plain_text", "No invoice for that month."),
        ("json_scalar", "42"),
        ("integer_that_would_lose_digits", '{"invoice_id":1234567890123456789}'),
        ("decimal_that_would_lose_digits", '{"amount":123456789012345.6789}'),
        ("number_that_overflows_to_null", '{"value":1e309}'),
        ("exponent_past_the_int_digit_limit", '{"value":1e-' + "1" * 5000 + "}"),
    ]
)
def test_keeps_a_tool_result_that_would_not_survive_parsing_as_its_exact_text(_name, content):
    [message] = messages_from(call_then_result(content), "assistant", prefix="out")

    assert message.parts == [tool_call("lookup", {}, content)]


@parameterized.expand(
    [
        ("rows", '{"rows": [1, 2]}', {"rows": [1, 2]}),
        (
            "numbers_the_browser_keeps_exactly",
            '{"id": 9007199254740991, "rate": 0.1, "scale": 1e300, "small": -2.5E-7, "zero": -0.0}',
            {"id": 9007199254740991, "rate": 0.1, "scale": 1e300, "small": -2.5e-7, "zero": -0.0},
        ),
        ("number_inside_a_string", '{"note": "id 1234567890123456789"}', {"note": "id 1234567890123456789"}),
    ]
)
def test_tool_result_json_string_parses_to_structure(_name, content, expected):
    [message] = messages_from(call_then_result(content), "assistant", prefix="out")

    assert message.parts == [tool_call("lookup", {}, expected)]


@parameterized.expand([("at_the_bound_parses", 200, True), ("past_the_bound_stays_text", 201, False)])
def test_tool_result_nesting_is_bounded(_name, depth, parses):
    content = "[" * depth + "]" * depth

    [message] = messages_from(call_then_result(content), "assistant", prefix="out")

    result = message.parts[0].result
    assert (result != content) is parses


def test_marks_unmatched_tool_results_as_internal_tool_messages():
    [message] = messages_from([{"role": "tool", "tool_call_id": "gone", "content": "late result"}], node=None)

    assert (message.role, message.is_internal, message.parts) == ("tool", True, [text("late result")])


def test_turns_non_text_content_items_into_attachments():
    [message] = messages_from(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this receipt?"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/r.png"}},
                ],
            }
        ],
        node=None,
    )

    assert message.parts == [
        text("What is in this receipt?"),
        contracts.TraceAttachmentPart(
            kind="attachment", media_type="image", name=None, mime_type=None, url="https://example.com/r.png"
        ),
    ]


def test_reads_an_audio_item_as_an_attachment_next_to_its_text():
    messages = messages_from(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this."},
                    {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "mp3"}},
                ],
            }
        ],
        node=None,
    )

    assert [part for message in messages for part in message.parts] == [
        text("Transcribe this."),
        contracts.TraceAttachmentPart(
            kind="attachment",
            media_type="audio",
            name=None,
            mime_type="audio/mp3",
            url="data:audio/mp3;base64,UklGRg==",
        ),
    ]


def test_reads_a_media_item_passed_through_as_json_text_as_an_attachment():
    compat: list[Any] = [
        {"role": "user", "content": '{"type":"image_url","image_url":{"url":"https://example.com/r.png"}}'}
    ]

    [message] = to_messages(compat, id_prefix="in", source_node_id=None, team_id=TEAM_ID)

    assert message.parts == [
        contracts.TraceAttachmentPart(
            kind="attachment", media_type="image", name=None, mime_type=None, url="https://example.com/r.png"
        )
    ]


def test_keeps_the_text_and_reasoning_summary_of_openai_responses_output_items():
    messages = messages_from(
        [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [{"type": "summary_text", "text": "Compare the two plans by seat price."}],
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "The team plan is cheaper for 5 seats.", "annotations": []}
                ],
            },
        ],
        "assistant",
        prefix="out",
    )

    assert [(m.role, m.parts, m.is_internal) for m in messages] == [
        (
            "assistant",
            [contracts.TraceThinkingPart(kind="thinking", text="Compare the two plans by seat price.")],
            True,
        ),
        ("assistant", [text("The team plan is cheaper for 5 seats.")], False),
    ]


def test_returns_nothing_for_no_messages():
    assert to_messages([], id_prefix="in", source_node_id=None, team_id=TEAM_ID) == []


def test_pairs_an_anthropic_tool_use_with_a_later_tool_result_and_keeps_thinking_separate():
    messages = messages_from(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me check the invoice."},
                    {"type": "tool_use", "id": "call-1", "name": "lookup_invoice", "input": {"month": "2026-08"}},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": '{"total_usd":180}'}],
            },
        ],
        "assistant",
        prefix="gen",
    )

    assert len(messages) == 2
    assert (messages[0].is_internal, messages[0].parts) == (
        True,
        [contracts.TraceThinkingPart(kind="thinking", text="Let me check the invoice.")],
    )
    assert (messages[1].is_internal, messages[1].parts) == (
        True,
        [tool_call("lookup_invoice", {"month": "2026-08"}, {"total_usd": 180})],
    )


def test_keeps_an_anthropic_tool_result_carrying_an_image_as_its_own_message_with_the_attachment():
    messages = messages_from(
        [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "call-1", "name": "take_screenshot", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
                        ],
                    }
                ],
            },
        ],
        "assistant",
        prefix="gen",
    )

    assert [(m.role, m.parts) for m in messages] == [
        ("assistant", [tool_call("take_screenshot", {})]),
        (
            "tool",
            [
                contracts.TraceAttachmentPart(
                    kind="attachment",
                    media_type="image",
                    name=None,
                    mime_type="image/png",
                    url="data:image/png;base64,AAAA",
                )
            ],
        ),
    ]


@parameterized.expand(
    [
        (
            "refusal",
            {"role": "assistant", "content": None, "refusal": "I cannot share account passwords."},
            "I cannot share account passwords.",
        ),
        (
            "spoken_reply",
            {
                "role": "assistant",
                "content": None,
                "audio": {"id": "audio-1", "transcript": "Your plan renews on Friday."},
            },
            "Your plan renews on Friday.",
        ),
    ]
)
def test_keeps_the_text_of_a_message_that_has_no_content(_name, message, expected_text):
    [result] = messages_from([message], "assistant", prefix="out")

    assert (result.role, result.parts) == ("assistant", [text(expected_text)])


def test_message_ids_count_skipped_engine_messages():
    compat: list[Any] = [
        {"role": "available tools", "content": "", "tools": []},
        {"role": "user", "content": "Hi"},
    ]

    [message] = to_messages(compat, id_prefix="in", source_node_id=None, team_id=TEAM_ID)

    assert message.id == "in-1"


DEEPLY_NESTED = "[" * 100_000


@parameterized.expand(
    [
        ("deeply_nested", DEEPLY_NESTED),
        ("overflowing_number", '{"limit": 1e400}'),
        ("integer_past_64_bits", '{"n": 100000000000000000000}'),
        ("lone_surrogate", '{"text": "\\ud800"}'),
        ("lone_surrogate_in_a_key", '{"\\udfff": 1}'),
    ]
)
def test_a_tool_call_argument_that_would_not_survive_parsing_stays_its_raw_text(_name, arguments):
    compat: list[Any] = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": arguments}}],
        }
    ]

    [message] = to_messages(compat, id_prefix="out", source_node_id=None, team_id=TEAM_ID)

    assert message.parts == [tool_call("f", arguments)]


def test_a_deeply_nested_tool_result_stays_its_raw_text():
    [message] = messages_from(call_then_result(DEEPLY_NESTED), "assistant", prefix="out")

    assert message.parts == [tool_call("lookup", {}, DEEPLY_NESTED)]


def nested_lists(depth: int) -> Any:
    value: Any = []
    for _ in range(depth - 1):
        value = [value]
    return value


@parameterized.expand(
    [
        (
            "arguments",
            [{"role": "assistant", "content": "", "tool_calls": [{"function": {"arguments": nested_lists(201)}}]}],
        ),
        (
            "result",
            [
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "function": {"arguments": {}}}]},
                {"role": "tool", "tool_call_id": "c", "content": nested_lists(201)},
            ],
        ),
        (
            "integer_past_64_bits",
            [{"role": "assistant", "content": "", "tool_calls": [{"function": {"arguments": {"n": 10**20}}}]}],
        ),
        (
            "lone_surrogate",
            [{"role": "assistant", "content": "", "tool_calls": [{"function": {"arguments": {"text": "\ud800"}}}]}],
        ),
        ("lone_surrogate_in_text", [{"role": "user", "content": [{"type": "text", "text": "\ud800"}]}]),
        (
            "lone_surrogate_in_a_tool_name",
            [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "\ud800", "arguments": {}}}]}],
        ),
        (
            "lone_surrogate_in_an_attachment_name",
            [{"role": "user", "content": [{"type": "file", "file": {"filename": "\ud800.pdf"}}]}],
        ),
    ]
)
def test_an_already_parsed_value_the_response_cannot_hold_fails_the_side(_name, compat):
    with pytest.raises(UnrenderableValueError):
        to_messages(compat, id_prefix="out", source_node_id=None, team_id=TEAM_ID)


def test_a_tool_result_with_a_multi_megabyte_string_parses_in_bounded_memory():
    content = '{"log": "' + "x" * 5_000_000 + '"}'

    tracemalloc.start()
    try:
        [message] = to_messages(call_then_result(content), id_prefix="out", source_node_id=None, team_id=TEAM_ID)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert message.parts == [tool_call("lookup", {}, {"log": "x" * 5_000_000})]
    assert peak < 4 * len(content)


# The value fails validation only halfway through, so the walk crosses a hundred thousand values before it ends.
WIDE_UNRENDERABLE_ARGUMENTS: list[CompatMessage] = [
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "f", "arguments": [*[[]] * 100_000, 10**20, *[[]] * 100_000]}}],
    }
]


def test_validating_a_wide_tool_value_holds_memory_to_its_depth():
    tracemalloc.start()
    try:
        with pytest.raises(UnrenderableValueError):
            to_messages(WIDE_UNRENDERABLE_ARGUMENTS, id_prefix="out", source_node_id=None, team_id=TEAM_ID)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 1_000_000


def test_validating_a_wide_tool_value_stops_at_the_deadline():
    with time_limit(0), pytest.raises(RecipeTimeoutError):
        to_messages(WIDE_UNRENDERABLE_ARGUMENTS, id_prefix="out", source_node_id=None, team_id=TEAM_ID)


def test_a_tool_result_longer_than_the_parse_cap_stays_its_raw_text():
    content = '{"rows": [1, 2, 3]}'

    with patch.object(values_module, "MAX_PARSE_CHARS", len(content) - 1):
        [message] = to_messages(call_then_result(content), id_prefix="out", source_node_id=None, team_id=TEAM_ID)

    assert message.parts == [tool_call("lookup", {}, content)]


@parameterized.expand(
    [
        ("past_the_deadline", lambda: time_limit(0), RecipeTimeoutError),
        (
            "over_the_output_budget",
            lambda: patch.object(run_limits_module, "MAX_OUTPUT_NODES", 1),
            RecipeOutputLimitError,
        ),
    ]
)
def test_parsing_tool_values_stops_at_the_read_limits(
    _name: str, limit: Callable[[], AbstractContextManager[object]], error: type[RecipeRuntimeError]
) -> None:
    with limit(), pytest.raises(error):
        to_messages(call_then_result('{"rows": [1, 2, 3]}'), id_prefix="out", source_node_id=None, team_id=TEAM_ID)

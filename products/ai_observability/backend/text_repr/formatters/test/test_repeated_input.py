import pytest

from .. import repeated_input
from ..repeated_input import RepeatedInput, RepeatedInputHistory


def _text(text: str, **extra: object) -> dict[str, object]:
    return {"role": "user", "content": [{"type": "text", "text": text, **extra}]}


def _tool_call(arguments: dict[str, object], **extra: object) -> dict[str, object]:
    return {"role": "assistant", "content": [{"type": "tool_use", "name": "verify", "input": arguments, **extra}]}


@pytest.mark.parametrize(
    "earlier,later,repeated",
    [
        pytest.param(_text("hi", cache_control={"type": "ephemeral"}), _text("hi"), True, id="block_cache_hint"),
        pytest.param(
            {**_text("hi"), "cache_control": {"type": "ephemeral"}}, _text("hi"), True, id="message_cache_hint"
        ),
        pytest.param(_tool_call({"x": 1}, caller="agent"), _tool_call({"x": 1}), True, id="block_caller"),
        pytest.param(
            _tool_call({"signature": "invalid"}), _tool_call({"signature": "valid"}), False, id="tool_argument"
        ),
        pytest.param(_text("hi"), _text("hi!"), False, id="text"),
        pytest.param(
            {"role": "tool", "content": [{"signature": "pending"}]},
            {"role": "tool", "content": [{"signature": "verified"}]},
            False,
            id="untyped_tool_result",
        ),
        pytest.param(
            {"role": "tool", "content": {"signature": "pending"}},
            {"role": "tool", "content": {"signature": "verified"}},
            False,
            id="tool_result_object",
        ),
    ],
)
def test_ignores_transport_metadata_only(earlier: object, later: object, repeated: bool) -> None:
    history = RepeatedInputHistory()
    history.add([earlier])

    assert history.add([later]) == (RepeatedInput(messages=1, generation=1) if repeated else None)


def test_names_the_latest_generation_that_sent_the_messages() -> None:
    history = RepeatedInputHistory()
    task_a, task_b = _text("task a"), _text("task b")
    history.add([task_a])
    history.add([task_b])
    history.add([task_a, _text("step")])

    assert history.add([task_a, _text("other step")]) == RepeatedInput(messages=1, generation=3)
    assert history.add([task_b]) == RepeatedInput(messages=1, generation=2)


def test_deeply_nested_messages_do_not_exceed_the_recursion_limit() -> None:
    nested: object = "leaf"
    for _ in range(5_000):
        nested = {"metadata": nested}
    message = {"role": "user", "content": "hi", "metadata": nested}
    history = RepeatedInputHistory()
    history.add([message])

    assert history.add([message]) == RepeatedInput(messages=1, generation=1)


def test_stops_indexing_new_messages_at_the_cap_but_still_matches_indexed_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repeated_input, "MAX_INDEXED_MESSAGES", 3)
    history = RepeatedInputHistory()
    history.add([_text(f"message {i}") for i in range(5)])

    assert history.add([_text(f"message {i}") for i in range(5)]) == RepeatedInput(messages=3, generation=1)

from typing import Any

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.message_lists import conversation_of, is_message_list

ROLE_MESSAGES = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
SERIALIZED_SYSTEM: dict[str, Any] = {
    "lc": 1,
    "type": "constructor",
    "id": ["langchain_core", "messages", "SystemMessage"],
    "kwargs": {"content": "be brief"},
}
PROMPT_VALUE: dict[str, Any] = {
    "lc": 1,
    "type": "constructor",
    "id": ["langchain_core", "prompt_values", "ChatPromptValue"],
    "kwargs": {"messages": [SERIALIZED_SYSTEM]},
}

PROMPT_VALUE_WITH_PARTIALS: dict[str, Any] = {
    **PROMPT_VALUE,
    "kwargs": {**PROMPT_VALUE["kwargs"], "partial_variables": {}},
}
UNKNOWN_CLASS: dict[str, Any] = {
    "lc": 1,
    "type": "constructor",
    "id": ["langchain_core", "messages", "FancyThing"],
    "kwargs": {},
}


@parameterized.expand(
    [
        ("role dicts", ROLE_MESSAGES, True),
        ("langchain typed dict", [{"type": "human", "content": "hi"}], True),
        ("langchain typed dict without content", [{"type": "human"}], False),
        ("serialized langchain message", [SERIALIZED_SYSTEM], True),
        ("serialized message of an unknown class", [SERIALIZED_SYSTEM, UNKNOWN_CLASS], False),
        (
            "serialized message with an object class name",
            [{**UNKNOWN_CLASS, "id": ["langchain_core", {"x": 1}]}],
            False,
        ),
        (
            "serialized message no recipe maps",
            [SERIALIZED_SYSTEM, {**UNKNOWN_CLASS, "id": ["langchain_core", "messages", "RemoveMessage"]}],
            False,
        ),
        (
            "serialized chat message chunk",
            [{**UNKNOWN_CLASS, "id": ["langchain_core", "messages", "ChatMessageChunk"]}],
            True,
        ),
        ("empty list", [], False),
        ("mixed list", [*ROLE_MESSAGES, {"foo": "bar"}], False),
        ("typed dict with a list type", [{"type": ["human"], "content": "hi"}], False),
        ("typed dict with an object type", [{"type": {"name": "human"}, "content": "hi"}], False),
        ("object wrapping messages", {"messages": ROLE_MESSAGES}, False),
        ("langchain prompt value", PROMPT_VALUE, False),
        ("not a list", {"role": "user"}, False),
        ("string", "hi", False),
    ]
)
def test_is_message_list(_name: str, value: object, expected: bool) -> None:
    assert is_message_list(value) is expected


@parameterized.expand(
    [
        ("bare list", ROLE_MESSAGES, ROLE_MESSAGES),
        ("only messages", {"messages": ROLE_MESSAGES}, ROLE_MESSAGES),
        ("messages with a sibling", {"messages": ROLE_MESSAGES, "sys_prompt": "x"}, None),
        ("empty messages", {"messages": []}, None),
        ("prompt value", PROMPT_VALUE, [SERIALIZED_SYSTEM]),
        (
            "prompt value with partial variables",
            PROMPT_VALUE_WITH_PARTIALS,
            None,
        ),
        ("messages holding a string", {"messages": "hi"}, None),
        ("not a conversation", {"role": "user"}, None),
    ]
)
def test_conversation_of(_name: str, value: Any, expected: list[Any] | None) -> None:
    assert conversation_of(value) == expected

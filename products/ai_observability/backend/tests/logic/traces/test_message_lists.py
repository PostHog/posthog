from parameterized import parameterized

from products.ai_observability.backend.logic.traces.message_lists import is_message_list

ROLE_MESSAGES = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
SERIALIZED_SYSTEM = {
    "lc": 1,
    "type": "constructor",
    "id": ["langchain_core", "messages", "SystemMessage"],
    "kwargs": {"content": "be brief"},
}
PROMPT_VALUE = {
    "lc": 1,
    "type": "constructor",
    "id": ["langchain_core", "prompt_values", "ChatPromptValue"],
    "kwargs": {"messages": [SERIALIZED_SYSTEM]},
}


@parameterized.expand(
    [
        ("role dicts", ROLE_MESSAGES, True),
        ("langchain typed dict", [{"type": "human", "content": "hi"}], True),
        ("langchain typed dict without content", [{"type": "human"}], False),
        ("serialized langchain message", [SERIALIZED_SYSTEM], False),
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

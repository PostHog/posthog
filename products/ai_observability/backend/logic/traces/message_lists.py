from collections.abc import Sequence

from ..message_normalizer.values import Value

_CHAT_MESSAGE_TYPES = frozenset({"system", "human", "ai", "tool", "function", "chat"})
# The classes the `langchain_envelope` built-in recipe gives a role, or whose `kwargs.role` it keeps. Any other class,
# such as `RemoveMessage`, would render as a default-role bubble that hides what it is, so it does not make a list a
# conversation. Keep in step with default_recipes/langchain_envelope.yaml.
_SERIALIZED_MESSAGE_CLASSES = frozenset(
    f"{kind}Message{suffix}" for kind in ("System", "Human", "AI", "Tool", "Chat") for suffix in ("", "Chunk")
)


def is_message_list(value: object) -> bool:
    return isinstance(value, list) and len(value) > 0 and all(_is_message_like(item) for item in value)


def conversation_of(value: Value) -> Sequence[Value] | None:
    # A wrapper unwraps only when `messages` is its only key, because any sibling, such as a system prompt, would
    # disappear from the messages view.
    if isinstance(value, list) and is_message_list(value):
        return value
    if isinstance(value, dict) and _is_langchain_envelope(value):
        value = value["kwargs"]
    if isinstance(value, dict) and value.keys() == {"messages"}:
        messages = value["messages"]
        if isinstance(messages, list) and is_message_list(messages):
            return messages
    return None


def _is_message_like(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if isinstance(item.get("role"), str):
        return True
    item_type = item.get("type")
    if isinstance(item_type, str) and item_type in _CHAT_MESSAGE_TYPES and "content" in item:
        return True
    return _is_serialized_message(item)


def _is_langchain_envelope(value: dict) -> bool:
    return value.get("lc") == 1 and value.get("type") == "constructor" and isinstance(value.get("kwargs"), dict)


def _is_serialized_message(item: dict) -> bool:
    class_path = item.get("id")
    return (
        _is_langchain_envelope(item)
        and isinstance(class_path, list)
        and len(class_path) > 0
        and isinstance(class_path[-1], str)
        and class_path[-1] in _SERIALIZED_MESSAGE_CLASSES
    )

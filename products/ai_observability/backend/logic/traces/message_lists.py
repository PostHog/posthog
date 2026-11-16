_CHAT_MESSAGE_TYPES = frozenset({"system", "human", "ai", "tool", "function", "chat"})


def is_message_list(value: object) -> bool:
    return isinstance(value, list) and len(value) > 0 and all(_is_message_like(item) for item in value)


def _is_message_like(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if isinstance(item.get("role"), str):
        return True
    item_type = item.get("type")
    return isinstance(item_type, str) and item_type in _CHAT_MESSAGE_TYPES and "content" in item

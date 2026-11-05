from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from .values import Value

ROLE_MAP: Final[Mapping[str, str]] = MappingProxyType(
    {
        "user": "user",
        "human": "user",
        "assistant": "assistant",
        "model": "assistant",
        "ai": "assistant",
        "bot": "assistant",
        "system": "system",
        "instructions": "system",
        "context": "system",
    }
)

AVAILABLE_TOOLS_ROLE: Final = "available tools"


def normalize_role(raw_role: Value, fallback: str) -> str:
    if not isinstance(raw_role, str):
        return fallback
    lowered = raw_role.lower()
    return ROLE_MAP.get(lowered, lowered)

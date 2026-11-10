from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from .run_limits import charge_output
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
THINKING_ROLE: Final = "assistant (thinking)"
TOOL_RESULT_ROLE: Final = "assistant (tool result)"


def normalize_role(raw_role: Value, fallback: str) -> str:
    if not isinstance(raw_role, str):
        return fallback
    # The role is event data of any length, and every message and scope keeps its own lowered copy.
    charge_output(chars=len(raw_role))
    lowered = raw_role.lower()
    return ROLE_MAP.get(lowered, lowered)

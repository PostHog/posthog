from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ACP (Agent Communication Protocol) notification methods
ACP_NOTIFICATION_TYPE = "notification"
ACP_METHOD_SESSION_UPDATE = "session/update"

# Sandbox-specific notification methods
TURN_COMPLETE_METHOD = "_posthog/turn_complete"

# Stop reasons
STOP_REASON_END_TURN = "end_turn"


def is_turn_complete(event: dict) -> bool:
    """Check if an ACP event signals the agent finished a turn.

    Matches both the raw ACP prompt response (``result.stopReason == "end_turn"``)
    and the synthetic ``_posthog/turn_complete`` notification.
    """
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return False
    notification = event.get("notification", {})
    if notification.get("method") == TURN_COMPLETE_METHOD:
        return True
    result = notification.get("result")
    return isinstance(result, dict) and result.get("stopReason") == STOP_REASON_END_TURN


# Session update types
ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK = "agent_message_chunk"


class SandboxSeedEvent(BaseModel):
    """Event written to the Redis stream to initialize it before the relay starts."""

    type: Literal["STREAM_STATUS"] = "STREAM_STATUS"
    status: str = "initializing"


class ACPTextContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    text: str = ""


class ACPSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    sessionUpdate: str
    content: ACPTextContent | None = None


class ACPSessionUpdateParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    update: ACPSessionUpdate | None = None


class ACPNotification(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str
    params: ACPSessionUpdateParams | dict[str, Any] | None = None

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ACP (Agent Communication Protocol) notification methods
ACP_NOTIFICATION_TYPE = "notification"
ACP_METHOD_SESSION_UPDATE = "session/update"

# Sandbox-specific notification methods
TURN_COMPLETE_METHOD = "_posthog/turn_complete"

# Stop reasons
STOP_REASON_END_TURN = "end_turn"
IDLE_RESUME_STOP_REASON = "idle_resume"

# pi agent event shapes
PI_EVENT_TYPE = "pi_event"
PI_TURN_COMPLETED_TYPE = "turn_completed"
PI_STOP_REASON_ERROR = "error"

PI_RUNTIME_ERROR_MESSAGE = "The agent stopped with a runtime error"


def is_turn_complete(event: Mapping[str, object]) -> bool:
    """Check if a sandbox event signals the agent finished a turn.

    Matches the raw ACP prompt response (``result.stopReason == "end_turn"``), the synthetic
    ``_posthog/turn_complete`` notification, and the pi-shaped ``turn_completed`` event. Every
    plane that closes a turn shares this predicate, so a run ends on the same event everywhere.

    True for a pi turn that ended in a runtime error too — the turn is over either way. Check
    `pi_turn_error` to tell the two apart before treating this as a successful completion.
    """
    if event.get("type") == PI_EVENT_TYPE:
        pi_event = event.get("event")
        return isinstance(pi_event, dict) and pi_event.get("type") == PI_TURN_COMPLETED_TYPE
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return False
    notification = event.get("notification")
    if not isinstance(notification, dict):
        return False
    if notification.get("method") == TURN_COMPLETE_METHOD:
        return True
    result = notification.get("result")
    return isinstance(result, dict) and result.get("stopReason") == STOP_REASON_END_TURN


def is_idle_resume_turn_complete(event: Mapping[str, object]) -> bool:
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return False
    notification = event.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != TURN_COMPLETE_METHOD:
        return False
    params = notification.get("params")
    return isinstance(params, dict) and params.get("stopReason") == IDLE_RESUME_STOP_REASON


def pi_turn_error(event: dict) -> bool:
    """True when a pi ``turn_completed`` event reports a terminal runtime failure.

    Pi keeps the same event shape for a normal end and a fatal error; only `stopReason`
    tells them apart. A caller must check this before signalling `is_turn_complete` as a
    successful completion, or a failed run gets recorded as one.
    """
    if event.get("type") != PI_EVENT_TYPE:
        return False
    pi_event = event.get("event")
    if not isinstance(pi_event, dict) or pi_event.get("type") != PI_TURN_COMPLETED_TYPE:
        return False
    return pi_event.get("stopReason") == PI_STOP_REASON_ERROR


def turn_completed_successfully(event: Mapping[str, object]) -> bool:
    """True when a turn-closing event reports ``end_turn`` as its stop reason.

    `is_turn_complete` answers "the turn is over". This answers "the turn is over and the
    agent finished its work", which a caller needs before it acts on the turn's result. The
    stop reason sits in a different place in each of the three envelopes.
    """
    if event.get("type") == PI_EVENT_TYPE:
        pi_event = event.get("event")
        if not isinstance(pi_event, dict) or pi_event.get("type") != PI_TURN_COMPLETED_TYPE:
            return False
        return pi_event.get("stopReason") == STOP_REASON_END_TURN
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return False
    notification = event.get("notification")
    if not isinstance(notification, dict):
        return False
    if notification.get("method") == TURN_COMPLETE_METHOD:
        params = notification.get("params")
        return isinstance(params, dict) and params.get("stopReason") == STOP_REASON_END_TURN
    result = notification.get("result")
    return isinstance(result, dict) and result.get("stopReason") == STOP_REASON_END_TURN


def turn_complete_trace_id(event: Mapping[str, object]) -> str | None:
    """The finished turn's gateway trace id, when the agent reported one.

    Only the synthetic ``_posthog/turn_complete`` notification carries it; the agent
    derives it from the ``traceparent`` the CLI sends and the gateway stamps the same id
    on the turn's ``$ai_generation`` events. Absent for a turn that ran without the
    traceparent hook, and for the raw ACP prompt response, which has no such field.
    """
    notification = event.get("notification")
    if not isinstance(notification, dict):
        return None
    params = notification.get("params")
    if not isinstance(params, dict):
        return None
    trace_id = params.get("traceId")
    return trace_id if isinstance(trace_id, str) and trace_id else None


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

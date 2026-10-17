from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import JsonValue

from posthog.dataclasses import frozen


@frozen
class MCPEventSubscriptionRecord:
    id: UUID
    arguments: dict[str, JsonValue]
    callback_host: str
    expires_at: datetime
    active: bool
    created_at: datetime


@frozen
class MCPEventSubscriptionPage:
    count: int
    results: list[MCPEventSubscriptionRecord]


class MCPCallbackError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Callback verification failed. Check the receiving endpoint and try again.")


class MCPEventSubscriptionNotFoundError(Exception):
    pass


class MCPEventSubscriptionPermissionError(Exception):
    pass


@frozen
class MCPEventData:
    event: str
    distinct_id: str
    properties: dict[str, JsonValue]


@frozen
class MCPEventEnvelope:
    eventId: str
    name: Literal["posthog.event_captured"]
    timestamp: datetime
    data: MCPEventData
    cursor: None

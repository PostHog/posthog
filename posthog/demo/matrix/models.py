import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from posthog.models.utils import UUIDT


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Dict[str, Any]
    timestamp: dt.datetime

    def __str__(self) -> str:
        return f"{self.event} @ {self.timestamp}"


@dataclass
class SimGroup:
    """A simulated group for group analytics."""

    type_index: Literal[0, 1, 2, 3, 4]
    key: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.key} (#{self.type_index})"


class SimPerson(ABC):
    """A simulated person."""

    first_seen_at: Optional[dt.datetime]
    internal_state: Dict[str, Any]
    properties: Dict[str, Any]
    events: List[SimEvent]

    def __init__(self):
        self.first_seen_at = None
        self.internal_state = {}
        self.properties = {}
        self.events = []

    @abstractmethod
    def simulate(self, *, start: dt.datetime, end: dt.datetime):
        raise NotImplementedError()

    def capture_event(self, event: str, timestamp: dt.datetime, properties: Optional[Dict[str, Any]] = None):
        if self.first_seen_at is None or self.first_seen_at > timestamp:
            self.first_seen_at = timestamp
        if properties:
            if properties.get("$set_once"):
                for key, value in properties["$set_once"].items():
                    if key not in self.properties:
                        self.properties[key] = value
            if properties.get("$set"):
                self.properties.update(properties["$set"])
        self.events.append(SimEvent(event=event, properties=properties or {}, timestamp=timestamp))

    @cached_property
    def distinct_id(self) -> Optional[UUID]:
        return self.first_seen_at and UUIDT(unix_time_ms=int(self.first_seen_at.timestamp() * 1000))

    def __str__(self) -> str:
        return str(self.distinct_id)

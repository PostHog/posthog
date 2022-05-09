import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from urllib.parse import urlparse
from posthog.models.utils import UUIDT

# Event name constants to be used in simulations
EVENT_PAGEVIEW = "$pageview"
EVENT_AUTOCAPTURE = "$autocapture"


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
    properties: Dict[str, Any]
    events: List[SimEvent]

    def __init__(self):
        self.first_seen_at = None
        self.properties = {}
        self.events = []

    @abstractmethod
    def simulate(self, *, start: dt.datetime, end: dt.datetime):
        raise NotImplementedError()

    def capture(self, event: str, timestamp: dt.datetime, properties: Dict[str, Any] = {}):
        if self.first_seen_at is None or self.first_seen_at > timestamp:
            self.first_seen_at = timestamp
        if properties.get("$set_once"):
            for key, value in properties["$set_once"].items():
                if key not in self.properties:
                    self.properties[key] = value
        if properties.get("$set"):
            self.properties.update(properties["$set"])
        properties["$timestamp"] = timestamp.isoformat()
        self.events.append(SimEvent(event=event, properties=properties or {}, timestamp=timestamp))

    def capture_pageview(self, timestamp: dt.datetime, properties: Dict[str, Any] = {}, *, current_url: str, referrer: Optional[str] = None):
        properties["$lib"] = "web"
        parsed_current_url = urlparse(current_url)
        properties["$current_url"] = current_url
        properties["$host"] = parsed_current_url.netloc
        properties["$pathname"] = parsed_current_url.path
        if referrer:
            parsed_referrer = urlparse(referrer)
            properties["$referrer"] = referrer
            properties["$referring_domain"] = parsed_referrer.netloc
        # TODO: properties["$os"]
        # TODO: properties["$browser"]
        # TODO: properties["$device_type"]
        self.capture(EVENT_PAGEVIEW, timestamp, properties)

    @cached_property
    def distinct_id(self) -> Optional[UUID]:
        return self.first_seen_at and UUIDT(unix_time_ms=int(self.first_seen_at.timestamp() * 1000))

    def __str__(self) -> str:
        return str(self.distinct_id)

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
)


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Dict[str, Any]
    timestamp: dt.datetime


@dataclass
class SimSnapshot:
    """A simulated session recording event."""

    snapshot_data: Dict[str, Any]
    session_id: str
    window_id: str
    timestamp: dt.datetime


@dataclass
class SimGroup:
    """A simulated group for group analytics."""

    type_index: Literal[0, 1, 2, 3, 4]
    key: str
    properties: Dict[str, Any] = field(default_factory=dict)


class SimPerson(ABC):
    """A simulated person."""

    first_seen_at: Optional[dt.datetime]
    internal_state: Dict[str, Any]
    properties: Dict[str, Any]
    events: List[SimEvent]
    snapshots: List[SimSnapshot]

    def __init__(self) -> None:
        self.first_seen_at = None
        self.internal_state = {}
        self.properties = {}
        self.events = []
        self.snapshots = []

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

    def capture_snapshot(self, snapshot_data: Any, session_id: str, window_id: str, timestamp: dt.datetime):
        self.snapshots.append(
            SimSnapshot(snapshot_data=snapshot_data, session_id=session_id, window_id=window_id, timestamp=timestamp)
        )

    @abstractmethod
    def sessions(
        self, initial_point_in_time: dt.datetime
    ) -> Generator[Tuple[dt.datetime, Optional["Effect"]], dt.datetime, None]:
        raise NotImplementedError


@dataclass
class Effect:
    """A session effect that runs a callback on the origin person's neighbor(s).
    This callback can for instance change the neighbor's properties, making them behave differently.
    If a target is specified, only that person is affected, otherwise all neighbors are.
    """

    origin: Tuple[int, int]
    target_offset: Optional[Tuple[int, int]]
    personal_callback: Callable[[SimPerson], None]

    def run(self, target_persons: Sequence[SimPerson]):
        for target_person in target_persons:
            self.personal_callback(target_person)

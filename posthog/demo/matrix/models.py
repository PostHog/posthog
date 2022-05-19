from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Tuple,
    TypeVar,
)
from urllib.parse import urlparse
from uuid import UUID

from django.utils import timezone

from posthog.models.utils import UUIDT

if TYPE_CHECKING:
    from posthog.demo.matrix.matrix import Cluster

# Event name constants to be used in simulations
EVENT_PAGEVIEW = "$pageview"
EVENT_PAGELEAVE = "$pageleave"
EVENT_AUTOCAPTURE = "$autocapture"
EVENT_IDENTIFY = "$identify"
EVENT_GROUP_IDENTIFY = "$groupidentify"

Properties = Dict[str, Any]
SP = TypeVar("SP", bound="SimPerson")
Effect = Callable[[SP], None]


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Properties
    timestamp: timezone.datetime

    def __str__(self) -> str:
        display = f"{self.timestamp} - {self.event} # {self.properties['$distinct_id']}"
        if current_url := self.properties.get("$current_url"):
            display += f" @ {current_url}"
        return display


@dataclass
class SimWebClient:
    """A client (i.e. browser), one of one or many used by a single person."""

    device_id: str
    anonymous_distinct_id: str
    device_type: str
    os: str
    browser: str

    active_distinct_id: str
    active_session_id: str

    def __init__(self, *, device_id: str, anonymous_distinct_id: str, device_type: str, os: str, browser: str):
        self.device_id = device_id
        self.anonymous_distinct_id = anonymous_distinct_id
        self.device_type = device_type
        self.os = os
        self.browser = browser
        self.active_distinct_id = anonymous_distinct_id

    def start_session(self, id: str):
        self.active_session_id = id


class SimPerson(ABC):
    """A simulation agent, representing an individual person."""

    _simulation_time: timezone.datetime  # Current simulation time, populated by running .simulate()
    _active_client: SimWebClient  # Client used by person, populated by running .simulate()
    _super_properties: Properties
    _end_pageview: Optional[Callable[[], None]]
    _groups: Dict[str, str]

    distinct_ids: List[str]
    properties: Properties

    events: List[SimEvent]
    scheduled_effects: Deque[Tuple[timezone.datetime, Effect]]

    kernel: bool  # Whether this person is the cluster kernel. Kernels are the most likely to become users
    cluster: "Cluster"
    x: int
    y: int

    def __init__(self, *, kernel: bool, cluster: "Cluster", x: int, y: int):
        self.distinct_ids = []
        self.properties = {}
        self.events = []
        self.scheduled_effects = Deque()
        self.kernel = kernel
        self.cluster = cluster
        self.x = x
        self.y = y

    def __str__(self) -> str:
        """Return person ID. Overriding this is recommended but optional."""
        return " / ".join(self.distinct_ids) if self.distinct_ids else "???"

    def simulate(self):
        if hasattr(self, "simulation_time"):
            raise Exception(f"Person {self} already has been simulated")
        self._simulation_time = self.cluster.start
        self._end_pageview = None
        device_type, os, browser = self.cluster.properties_provider.device_type_os_browser()
        self._active_client = SimWebClient(
            device_id=str(UUIDT(int(self._simulation_time.timestamp()), seeded_random=self.cluster.random)),
            anonymous_distinct_id=str(UUID(int=self.cluster.random.getrandbits(128))),
            device_type=device_type,
            os=os,
            browser=browser,
        )
        self._groups = {}
        self._super_properties = {}
        self.distinct_ids.append(self._active_client.anonymous_distinct_id)
        while self._simulation_time <= self.cluster.end:
            self._simulate_session()
            if self._end_pageview is not None:
                self._end_pageview()  # type: ignore
                self._end_pageview = None

    @abstractmethod
    def _simulate_session(self):
        """Simulation of a single session based on current agent state."""
        if self.scheduled_effects and self.scheduled_effects[0][0] <= self._simulation_time:
            _, effect = self.scheduled_effects.popleft()
            effect(self)

    def _affect_neighbors(self, effect: Effect):
        """Schedule the provided effect for all neighbors.

        Because agents are currently simulated synchronously, the effect will only work on those who
        haven't been simulated yet, but that's OK. The mechanism still has interesting results.
        """
        for neighbor in self.cluster._list_neighbors(self.x, self.y):
            neighbor.schedule_effect(self._simulation_time, effect)

    def schedule_effect(self, timestamp: timezone.datetime, effect: Effect):
        self.scheduled_effects.append((timestamp, effect))

    def _advance_timer(self, seconds: float):
        self._simulation_time += timezone.timedelta(seconds=seconds)

    def _capture(
        self,
        event: str,
        properties: Optional[Properties] = None,
        *,
        current_url: Optional[str] = None,
        referrer: Optional[str] = None,
    ):
        combined_properties: Properties = {
            "$distinct_id": self._active_client.active_distinct_id,
            "$lib": "web",
            "$device_type": self._active_client.device_type,
            "$os": self._active_client.os,
            "$browser": self._active_client.browser,
            "$session_id": self._active_client.active_session_id,
            "$device_id": self._active_client.device_id,
            "$groups": self._groups.copy(),
            "$timestamp": self._simulation_time.isoformat(),
            "$time": self._simulation_time.timestamp(),
        }
        if self._super_properties:
            combined_properties.update(self._super_properties)
            if "$set" not in combined_properties:
                combined_properties["$set"] = {}
            combined_properties["$set"].update(self._super_properties)
        if current_url:
            parsed_current_url = urlparse(current_url)
            combined_properties["$current_url"] = current_url
            combined_properties["$host"] = parsed_current_url.netloc
            combined_properties["$pathname"] = parsed_current_url.path
        if referrer:
            parsed_referrer = urlparse(referrer)
            combined_properties["$referrer"] = referrer
            combined_properties["$referring_domain"] = parsed_referrer.netloc
        # Application of event
        if properties:
            combined_properties.update(properties)
        if combined_properties.get("$set_once"):
            for key, value in combined_properties["$set_once"].items():
                if key not in self.properties:
                    self.properties[key] = value
        if combined_properties.get("$set"):
            self.properties.update(combined_properties["$set"])
        # Saving
        self.events.append(SimEvent(event=event, properties=combined_properties or {}, timestamp=self._simulation_time))

    def _capture_pageview(
        self, current_url: str, properties: Optional[Properties] = None, *, referrer: Optional[str] = None
    ):
        if self._end_pageview is not None:
            self._end_pageview()
        self._advance_timer(self.cluster.random.uniform(0.05, 0.3))  # A page doesn't load instantly
        self._capture(EVENT_PAGEVIEW, properties, current_url=current_url, referrer=referrer)
        self._end_pageview = lambda: self._capture(EVENT_PAGELEAVE, current_url=current_url, referrer=referrer)

    def _identify(self, distinct_id: Optional[str], set_properties: Optional[Properties] = None):
        if set_properties is None:
            set_properties = {}
        identify_properties = {"$distinct_id": self._active_client.active_distinct_id, "$set": set_properties}
        if distinct_id:
            self._active_client.active_distinct_id = distinct_id
            identify_properties["$user_id"] = distinct_id
            if distinct_id not in self.distinct_ids:
                self.distinct_ids.append(distinct_id)
        self._capture(EVENT_IDENTIFY, identify_properties)

    def _reset(self):
        self._active_client.active_distinct_id = self._active_client.anonymous_distinct_id

    def _register(self, super_properties: Properties):
        """Register super properties. Differently from posthog-js, these also are set on the person."""
        self._super_properties.update(super_properties)

    def _group_identify(self, group_type: str, group_key: str, set_properties: Optional[Properties] = None):
        if set_properties is None:
            set_properties = {}
        self._groups[group_type] = group_key
        self.cluster.matrix.update_group(group_type, group_key, set_properties)
        self._capture(
            EVENT_GROUP_IDENTIFY, {"$group_type": group_type, "$group_key": group_key, "$group_set": set_properties}
        )

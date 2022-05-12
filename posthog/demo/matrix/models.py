import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from typing_extensions import Self

from posthog.models.utils import UUIDT

if TYPE_CHECKING:
    from posthog.demo.matrix.matrix import Cluster

# Event name constants to be used in simulations
EVENT_PAGEVIEW = "$pageview"
EVENT_PAGELEAVE = "$pageleave"
EVENT_AUTOCAPTURE = "$autocapture"
EVENT_IDENTIFY = "$identify"
EVENT_GROUP_IDENTIFY = "$groupidentify"


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Dict[str, Any]
    timestamp: dt.datetime

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

    simulation_time: dt.datetime  # Current simulation time, populated by running .simulate()
    active_client: SimWebClient  # Client used by person, populated by running .simulate()

    first_seen_at: Optional[dt.datetime]
    distinct_ids: List[str]
    properties: Dict[str, Any]
    events: List[SimEvent]

    kernel: bool  # Whether this person is the cluster kernel. Kernels are the most likely to become users
    cluster: "Cluster"
    x: int
    y: int
    update_group: Callable[[str, str, Dict[str, Any]], None]

    def __init__(
        self,
        *,
        kernel: bool,
        cluster: "Cluster",
        x: int,
        y: int,
        update_group: Callable[[str, str, Dict[str, Any]], None],
    ):
        self.first_seen_at = None
        self.distinct_ids = []
        self.properties = {}
        self.events = []
        self.kernel = kernel
        self.cluster = cluster
        self.x = x
        self.y = y
        self.update_group = update_group

    def __str__(self) -> str:
        """Return person ID. Overriding this is recommended but optional."""
        return " / ".join(self.distinct_ids) if self.distinct_ids else "???"

    def simulate(self):
        if hasattr(self, "simulation_time"):
            raise Exception(f"Person {self} already has been simulated")
        self.simulation_time = self.cluster.start
        device_type, os, browser = self.cluster.properties_provider.device_type_os_browser()
        self.active_client = SimWebClient(
            device_id=str(UUIDT(int(self.simulation_time.timestamp()), seeded_random=self.cluster.random)),
            anonymous_distinct_id=str(UUID(int=self.cluster.random.getrandbits(128))),
            device_type=device_type,
            os=os,
            browser=browser,
        )
        self.distinct_ids.append(self.active_client.anonymous_distinct_id)
        while self.simulation_time <= self.cluster.end:
            self._simulate_session()

    @abstractmethod
    def _simulate_session(self):
        """Simulation of a single session based on current agent state."""

    def _affect_neighbors(self, effect: Callable[[Self], None]):
        for neighbor in self.cluster._list_neighbors(self.x, self.y):
            effect(neighbor)

    def _advance_timer(self, seconds: float):
        self.simulation_time += dt.timedelta(seconds=seconds)

    def _capture(
        self,
        event: str,
        properties: Optional[Dict[str, Any]] = None,
        *,
        current_url: Optional[str] = None,
        referrer: Optional[str] = None,
    ):
        combined_properties: Dict[str, Any] = {
            "$lib": "web",
            "$distinct_id": self.active_client.active_distinct_id,
            "$device_type": self.active_client.device_type,
            "$os": self.active_client.os,
            "$browser": self.active_client.browser,
            "$session_id": self.active_client.active_session_id,
            "$device_id": self.active_client.device_id,
        }
        if current_url:
            parsed_current_url = urlparse(current_url)
            combined_properties["$current_url"] = current_url
            combined_properties["$host"] = parsed_current_url.netloc
            combined_properties["$pathname"] = parsed_current_url.path
        if referrer:
            parsed_referrer = urlparse(referrer)
            combined_properties["$referrer"] = referrer
            combined_properties["$referring_domain"] = parsed_referrer.netloc
        if properties:
            combined_properties.update(properties)
        if self.first_seen_at is None:
            self.first_seen_at = self.simulation_time
        if combined_properties.get("$set_once"):
            for key, value in combined_properties["$set_once"].items():
                if key not in self.properties:
                    self.properties[key] = value
        if combined_properties.get("$set"):
            self.properties.update(combined_properties["$set"])
        combined_properties["$timestamp"] = self.simulation_time.isoformat()
        self.events.append(SimEvent(event=event, properties=combined_properties or {}, timestamp=self.simulation_time))

    def _capture_pageview(
        self, current_url: str, properties: Optional[Dict[str, Any]] = None, *, referrer: Optional[str] = None
    ) -> Callable[[], None]:
        self._capture(EVENT_PAGEVIEW, properties, current_url=current_url, referrer=referrer)
        return lambda: self._capture(EVENT_PAGELEAVE, current_url=current_url, referrer=referrer)

    def _identify(self, distinct_id: str, set_properties: Optional[Dict[str, Any]] = None):
        if set_properties is None:
            set_properties = {}
        self.active_client.active_distinct_id = distinct_id
        self._capture(EVENT_IDENTIFY, {"$set": set_properties})
        if distinct_id not in self.distinct_ids:
            self.distinct_ids.append(distinct_id)

    def _reset(self):
        self.active_client.active_distinct_id = self.active_client.anonymous_distinct_id

    def _group_identify(self, group_type: str, group_key: str, set_properties: Optional[Dict[str, Any]] = None):
        if set_properties is None:
            set_properties = {}
        self.update_group(group_type, group_key, set_properties)
        self._capture(
            EVENT_GROUP_IDENTIFY, {"$group_type": group_type, "$group_key": group_key, "$group_set": set_properties}
        )

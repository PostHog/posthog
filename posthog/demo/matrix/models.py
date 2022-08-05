import datetime as dt
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Deque,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)
from urllib.parse import urlparse
from uuid import UUID

import pytz

from posthog.models.utils import UUIDT

if TYPE_CHECKING:
    from posthog.demo.matrix.matrix import Cluster

# Event name constants to be used in simulations
EVENT_PAGEVIEW = "$pageview"
EVENT_PAGELEAVE = "$pageleave"
EVENT_AUTOCAPTURE = "$autocapture"
EVENT_IDENTIFY = "$identify"
EVENT_GROUP_IDENTIFY = "$groupidentify"

PROPERTY_GEOIP_COUNTRY_CODE = "$geoip_country_code"

Properties = Dict[str, Any]
SP = TypeVar("SP", bound="SimPerson")
Effect = Callable[[SP], Any]


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    properties: Properties
    timestamp: dt.datetime

    def __str__(self) -> str:
        separator = (
            "-" if self.timestamp < dt.datetime.now(dt.timezone.utc) else "+"
        )  # Future events are denoted by a '+'
        display = f"{self.timestamp} {separator} {self.event} # {self.properties['$distinct_id']}"
        if current_url := self.properties.get("$current_url"):
            display += f" @ {current_url}"
        return display


@dataclass
class SimWebClient:
    """A client (i.e. browser), one of one or many used by a single person."""

    device_id: str
    device_type: str
    os: str
    browser: str

    active_distinct_id: str
    active_session_id: str

    def __init__(self, *, device_id: str, device_type: str, os: str, browser: str):
        self.device_id = device_id
        self.device_type = device_type
        self.os = os
        self.browser = browser
        self.active_distinct_id = device_id

    def start_session(self, id: str):
        self.active_session_id = id


class SimPerson(ABC):
    """A simulation agent, representing an individual person."""

    # Cluster-level metadata
    cluster: "Cluster"
    kernel: bool  # Whether this person is the cluster kernel. Kernels are the most likely to become users
    x: int
    y: int

    # Constant properties
    country_code: str
    timezone: str

    # Exposed state - present
    past_events: List[SimEvent]
    future_events: List[SimEvent]
    scheduled_effects: Deque[Tuple[dt.datetime, Effect]]

    # Exposed state - at `now`
    distinct_ids_at_now: Set[str]
    properties_at_now: Properties

    # Internal state
    _simulation_time: dt.datetime  # Current simulation time, populated by running .simulate()
    _active_client: SimWebClient  # Client used by person, populated by running .simulate()
    _super_properties: Properties
    _end_pageview: Optional[Callable[[], None]]
    _groups: Dict[str, str]
    _distinct_ids: Set[str]
    _properties: Properties

    @abstractmethod
    def __init__(self, *, kernel: bool, cluster: "Cluster", x: int, y: int):
        self._distinct_ids = set()
        self._properties = {}
        self.past_events = []
        self.future_events = []
        self.scheduled_effects = Deque()
        self.kernel = kernel
        self.cluster = cluster
        self.x = x
        self.y = y

    def __str__(self) -> str:
        """Return person ID. Overriding this is recommended but optional."""
        return " / ".join(self._distinct_ids) if self._distinct_ids else "???"

    # Helpers

    @property
    def all_events(self) -> Iterable[SimEvent]:
        return chain(self.past_events, self.future_events)

    @property
    def first_event(self) -> Optional[SimEvent]:
        return self.past_events[0] if self.past_events else (self.future_events[0] if self.future_events else None)

    @property
    def last_event(self) -> Optional[SimEvent]:
        return self.future_events[-1] if self.future_events else (self.past_events[-1] if self.past_events else None)

    # Public methods

    def simulate(self):
        """Synchronously simulate this person's behavior for the whole duration of the simulation."""
        if hasattr(self, "simulation_time"):
            raise Exception(f"Person {self} already has been simulated")
        self._simulation_time = self.cluster.start.astimezone(pytz.timezone(self.timezone))
        self._end_pageview = None
        device_type, os, browser = self.cluster.properties_provider.device_type_os_browser()
        self._active_client = SimWebClient(
            device_id=str(UUID(int=self.cluster.random.getrandbits(128))),
            device_type=device_type,
            os=os,
            browser=browser,
        )
        self._groups = {}
        self._super_properties = {}
        self._distinct_ids.add(self._active_client.device_id)
        while self._simulation_time <= self.cluster.end:
            self._fast_forward_to_next_session()
            self._apply_due_effects()
            self._active_client.start_session(str(self.roll_uuidt()))
            self._simulate_session()
            if self._end_pageview is not None:  # Let's assume the page is always left at the end
                self._end_pageview()
                self._end_pageview = None

    def schedule_effect(self, timestamp: dt.datetime, effect: Effect):
        """Schedule an effect to apply at a given time.

        An effect is a function that runs on the person, so it can change the person's state."""
        self.scheduled_effects.append((timestamp, effect))

    # Abstract methods

    @abstractmethod
    def _fast_forward_to_next_session(self):
        """Intelligently advance timer to the time of the next session."""
        raise NotImplementedError()

    @abstractmethod
    def _simulate_session(self):
        """Simulate a single session based on current agent state. This is how subclasses can define user behavior."""
        raise NotImplementedError()

    # Neighbor state

    def _affect_neighbors(self, effect: Effect):
        """Schedule the provided effect lambda for all neighbors.

        Because agents are currently simulated synchronously, the effect will only work on those who
        haven't been simulated yet, but that's OK - the results are interesting this way too.
        """
        for neighbor in self.cluster._list_neighbors(self.x, self.y):
            neighbor.schedule_effect(self._simulation_time, effect)

    # Person state

    def _move_needle(self, attr: str, delta: float):
        """Move the person's property by the given delta. Useful for defining effects."""
        setattr(self, attr, getattr(self, attr) + delta)

    def _apply_due_effects(self):
        while True:
            if not self.scheduled_effects or self.scheduled_effects[0][0] > self._simulation_time:
                break
            _, effect = self.scheduled_effects.popleft()
            effect(self)

    def _advance_timer(self, seconds: float):
        """Advance simulation time by the given amount of time."""
        self._simulation_time += dt.timedelta(seconds=seconds)

    def _take_snapshot_at_now(self):
        """Take a snapshot of person state at simulation `now` time, for dividing past and future events."""
        self.distinct_ids_at_now = self._distinct_ids.copy()
        self.properties_at_now = deepcopy(self._properties)

    # Analyics

    def _capture(
        self,
        event: str,
        properties: Optional[Properties] = None,
        *,
        current_url: Optional[str] = None,
        referrer: Optional[str] = None,
    ):
        """Capture an arbitrary event. Similar to JS `posthog.capture()`."""
        if self._simulation_time > self.cluster.now:
            # If we've just reached matrix's now, take a snapshot of the current state
            if not hasattr(self, "distinct_ids_at_now"):
                self._take_snapshot_at_now()
            events = self.future_events
        else:
            events = self.past_events

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
        if current_url:
            parsed_current_url = urlparse(current_url)
            combined_properties["$current_url"] = current_url
            combined_properties["$host"] = parsed_current_url.netloc
            combined_properties["$pathname"] = parsed_current_url.path
        if referrer:
            referrer_properties = {
                "$referrer": referrer,
                "$referring_domain": urlparse(referrer).netloc,
            }
            self._register(referrer_properties)
            self._identify(self._active_client.active_distinct_id, referrer_properties)
            combined_properties.update(referrer_properties)
        # Application of event
        if properties:
            combined_properties.update(properties)
        # GeoIP
        if "$set" not in combined_properties:
            combined_properties["$set"] = {}
        combined_properties[PROPERTY_GEOIP_COUNTRY_CODE] = self.country_code
        combined_properties["$set"][PROPERTY_GEOIP_COUNTRY_CODE] = self.country_code
        # $set/$set_once processing
        if combined_properties.get("$set_once"):
            for key, value in combined_properties["$set_once"].items():
                if key not in self._properties:
                    self._properties[key] = value
        if combined_properties.get("$set"):
            self._properties.update(combined_properties["$set"])
        # Saving
        events.append(SimEvent(event=event, properties=combined_properties or {}, timestamp=self._simulation_time))

    def _capture_pageview(
        self, current_url: str, properties: Optional[Properties] = None, *, referrer: Optional[str] = None
    ):
        """Capture a $pageview event. $pageleave is handled implicitly."""
        if self._end_pageview is not None:
            self._end_pageview()
        self._advance_timer(self.cluster.random.uniform(0.05, 0.3))  # A page doesn't load instantly
        self._capture(EVENT_PAGEVIEW, properties, current_url=current_url, referrer=referrer)
        self._end_pageview = lambda: self._capture(EVENT_PAGELEAVE, current_url=current_url, referrer=referrer)

    def _identify(self, distinct_id: Optional[str], set_properties: Optional[Properties] = None):
        """Identify person in active client. Similar to JS `posthog.identify()`.

        Use with distinct_id=None for `posthog.people.set()`-like behavior."""
        if set_properties is None:
            set_properties = {}
        identify_properties = {"$distinct_id": self._active_client.active_distinct_id, "$set": set_properties}
        if distinct_id:
            if self._active_client.device_id == self._active_client.active_distinct_id:
                identify_properties["$anon_distinct_id"] = self._active_client.device_id
            identify_properties["$user_id"] = distinct_id
            self._active_client.active_distinct_id = distinct_id
            self._distinct_ids.add(distinct_id)
        self._capture(EVENT_IDENTIFY, identify_properties)

    def _reset(self):
        """Reset active client, for instance when the user logs out. Similar to JS `posthog.reset()`."""
        self._active_client.active_distinct_id = self._active_client.device_id

    def _register(self, super_properties: Properties):
        """Register super properties. Similar to JS `posthog.register()`."""
        self._super_properties.update(super_properties)

    def _unregister(self, *super_property_keys: str):
        """Removes super properties. Similar to JS `posthog.unregister()`."""
        for key in super_property_keys:
            self._super_properties.pop(key)

    def _group(self, group_type: str, group_key: str, set_properties: Optional[Properties] = None):
        """Link the person to the specified group. Similar to JS `posthog.group()`."""
        if set_properties is None:
            set_properties = {}
        self._groups[group_type] = group_key
        self.cluster.matrix.update_group(group_type, group_key, set_properties)
        self._capture(
            EVENT_GROUP_IDENTIFY, {"$group_type": group_type, "$group_key": group_key, "$group_set": set_properties}
        )

    # Utilities

    def roll_uuidt(self, at_timestamp: Optional[dt.datetime] = None) -> UUIDT:
        if at_timestamp is None:
            at_timestamp = self._simulation_time
        return UUIDT(int(at_timestamp.timestamp() * 1000), seeded_random=self.cluster.random)

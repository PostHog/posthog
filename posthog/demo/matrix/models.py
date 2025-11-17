import datetime as dt
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum, auto
from itertools import chain
from typing import TYPE_CHECKING, Any, Generic, Literal, Optional, TypeVar
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from posthog.demo.matrix.matrix import Cluster, Matrix

# Refer to https://github.com/PostHog/posthog-ai-costs-app/tree/main/src/ai-cost-data for missing models
LLM_COSTS_BY_MODEL = {
    "gpt-4o": {"prompt_token": 2.5 / 1e6, "completion_token": 10 / 1e6},
    "gpt-4o-mini": {"prompt_token": 0.15 / 1e6, "completion_token": 0.6 / 1e6},
}

SP = TypeVar("SP", bound="SimPerson")
EffectCallback = Callable[[SP], Any]
EffectCondition = Callable[[SP], bool]


@dataclass
class Effect(Generic[SP]):
    """An effect is in essence a callback that runs on the person and can change the person's state."""

    class Target(Enum):
        SELF = auto()
        ALL_NEIGHBORS = auto()
        RANDOM_NEIGHBOR = auto()

    timestamp: dt.datetime
    callback: EffectCallback[SP]
    source: "SimPerson"
    target: Target
    condition: Optional[EffectCondition[SP]]


# Event name constants to be used in simulations
EVENT_PAGEVIEW = "$pageview"
EVENT_PAGELEAVE = "$pageleave"
EVENT_AUTOCAPTURE = "$autocapture"
EVENT_IDENTIFY = "$identify"
EVENT_GROUP_IDENTIFY = "$groupidentify"

PROPERTY_GEOIP_COUNTRY_CODE = "$geoip_country_code"
PROPERTY_GEOIP_REGION = "$geoip_subdivision_1_code"
PROPERTY_GEOIP_CITY = "$geoip_city_name"
PROPERTY_TIMEZONE = "$timezone"
PROPERTY_TIMEZONE_OFFSET = "$timezone_offset"
PROPERTY_BROWSER_LANGUAGE = "$browser_language"

UTM_QUERY_PROPERTIES = {"utm_source", "utm_campaign", "utm_medium", "utm_term", "utm_content"}


# Properties who get `$set_once` implicitly as `$initial_foo` - source of truth in plugin-server/src/utils/db/utils.ts
PROPERTIES_WITH_IMPLICIT_INITIAL_VALUE_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "gclid",
    "fbclid",
    "$browser",
    "$browser_version",
    "$device_type",
    "$current_url",
    "$pathname",
    "$os",
    "$referring_domain",
    "$referrer",
}

Properties = dict[str, Any]


class SimSessionIntent(Enum):
    """An enumeration of session intents.

    An intent is determined for each session a user starts, and it informs their behavior during that session."""

    pass


@dataclass
class SimEvent:
    """A simulated event."""

    event: str
    distinct_id: str
    properties: Properties
    timestamp: dt.datetime
    person_id: UUID
    person_properties: Properties
    person_created_at: dt.datetime
    group0_properties: Optional[Properties] = None
    group1_properties: Optional[Properties] = None
    group2_properties: Optional[Properties] = None
    group3_properties: Optional[Properties] = None
    group4_properties: Optional[Properties] = None
    group0_created_at: Optional[dt.datetime] = None
    group1_created_at: Optional[dt.datetime] = None
    group2_created_at: Optional[dt.datetime] = None
    group3_created_at: Optional[dt.datetime] = None
    group4_created_at: Optional[dt.datetime] = None

    def __str__(self) -> str:
        separator = "-" if self.timestamp < dt.datetime.now(dt.UTC) else "+"  # Future events are denoted by a '+'
        display = f"{self.timestamp} {separator} {self.event} # {self.distinct_id}"
        if current_url := self.properties.get("$current_url"):
            display += f" @ {current_url}"
        return display


class SimClient(ABC):
    """An abstract PostHog client."""

    LIB_NAME: str  # Used for `$lib` property

    matrix: "Matrix"

    @abstractmethod
    def _get_person(self, distinct_id: str) -> "SimPerson":
        raise NotImplementedError()

    def _capture_raw(self, event: str, properties: Optional[Properties] = None, *, distinct_id: str) -> None:
        person = self._get_person(distinct_id)
        timestamp = person.cluster.simulation_time
        combined_properties: Properties = {
            "$lib": self.LIB_NAME,
            "$timestamp": timestamp.isoformat(),
            "$time": timestamp.timestamp(),
        }
        if properties:
            combined_properties.update(properties or {})
        # Saving
        person._append_event(event, combined_properties, distinct_id=distinct_id, timestamp=timestamp)


class SimServerClient(SimClient):
    """A Python server client for simulating server-side tracking."""

    LIB_NAME = "posthog-python"

    def __init__(self, matrix: "Matrix"):
        self.matrix = matrix

    def _get_person(self, distinct_id: str):
        return self.matrix.distinct_id_to_person[distinct_id]

    def capture(self, event: str, properties: Optional[Properties] = None, *, distinct_id: str) -> None:
        self._capture_raw(event, properties, distinct_id=distinct_id)

    def capture_ai_generation(
        self,
        *,
        distinct_id: str,
        input: list[dict],
        output_content: str,
        latency: float,
        base_url: str = "https://api.openai.com/v1",
        provider: str = "openai",
        model: str = "gpt-4o",
        trace_id: Optional[str] = None,
        http_status: int = 200,
    ):
        """Capture an AI generation event."""
        input_tokens = sum(len(self.matrix.gpt_4o_encoding.encode(message["content"])) for message in input)
        output_tokens = len(self.matrix.gpt_4o_encoding.encode(output_content))
        input_cost_usd = input_tokens * LLM_COSTS_BY_MODEL[model]["prompt_token"]
        output_cost_usd = output_tokens * LLM_COSTS_BY_MODEL[model]["completion_token"]
        self.capture(
            "$ai_generation",
            {
                "$ai_base_url": base_url,
                "$ai_provider": provider,
                "$ai_model": model,
                "$ai_http_status": http_status,
                "$ai_input_tokens": input_tokens,
                "$ai_output_tokens": output_tokens,
                "$ai_input_cost_usd": input_cost_usd,
                "$ai_output_cost_usd": output_cost_usd,
                "$ai_total_cost_usd": input_cost_usd + output_cost_usd,
                "$ai_input": input,
                "$ai_output": {
                    "choices": [
                        {
                            "content": output_content,
                            "role": "assistant",
                        }
                    ]
                },
                "$ai_latency": latency,
                "$ai_trace_id": trace_id or str(uuid4()),
            },
            distinct_id=distinct_id,
        )

    @contextmanager
    def trace_ai(
        self,
        *,
        distinct_id: str,
        input_state: Any,
        trace_id: Optional[str] = None,
    ) -> Generator[tuple[str, Callable], None, None]:
        """Capture an AI generation event."""
        trace_id = trace_id or str(uuid4())
        output_state = None

        def set_trace_output(output: Any):
            nonlocal output_state
            if output_state is not None:
                raise ValueError("Output already set for this trace")
            output_state = output

        try:
            yield trace_id, set_trace_output
        finally:
            self.capture(
                "$ai_trace",
                {
                    "$ai_input_state": input_state,
                    "$ai_output_state": output_state,
                    "$ai_span_name": "SpikeChain",
                    "$ai_trace_id": trace_id,
                },
                distinct_id=distinct_id,
            )


class SimBrowserClient(SimClient):
    """A browser client for simulating client-side tracking."""

    LIB_NAME = "web"

    # Parent
    person: "SimPerson"

    # Properties
    device_id: str
    device_type: str
    os: str
    browser: str

    # State
    active_distinct_id: str
    active_session_id: Optional[str]
    super_properties: Properties
    current_url: Optional[str]
    is_logged_in: bool

    def __init__(self, person: "SimPerson"):
        self.person = person
        self.matrix = person.cluster.matrix
        (
            self.device_type,
            self.os,
            self.browser,
        ) = self.person.cluster.properties_provider.device_type_os_browser()
        self.device_id = str(UUID(int=self.person.cluster.random.getrandbits(128)))
        self.active_distinct_id = self.device_id  # Pre-`$identify`, the device ID is used as the distinct ID
        self.active_session_id = None
        self.super_properties = {}
        self.current_url = None
        self.is_logged_in = False

    def __enter__(self):
        """Start session within client."""
        self.active_session_id = str(self.person.cluster.roll_uuid_v7())

    def __exit__(self, exc_type, exc_value, exc_traceback):
        """End session within client. Handles `$pageleave` event."""
        if self.current_url is not None:
            self.capture(EVENT_PAGELEAVE)
            self.current_url = None

    def _get_person(self, _: str):
        return self.person

    def capture(self, event: str, properties: Optional[Properties] = None):
        """Capture an arbitrary event. Similar to JS `posthog.capture()`."""
        combined_properties: Properties = {
            "$device_type": self.device_type,
            "$os": self.os,
            "$browser": self.browser,
            "$session_id": self.active_session_id,
            "$device_id": self.device_id,
        }
        if "$set" not in combined_properties:
            combined_properties["$set"] = {}
        if self.super_properties:
            combined_properties.update(self.super_properties)
        if self.current_url is not None:
            parsed_current_url = urlparse(self.current_url)
            parsed_current_url_query = parse_qs(parsed_current_url.query)
            combined_properties["$current_url"] = self.current_url
            combined_properties["$host"] = parsed_current_url.netloc
            combined_properties["$pathname"] = parsed_current_url.path
            for utm_key in UTM_QUERY_PROPERTIES:
                if utm_key in parsed_current_url_query:
                    utm_value = parsed_current_url_query[utm_key][0]
                    combined_properties[utm_key] = utm_value
                    combined_properties["$set"][utm_key] = utm_value
        if properties:
            if referrer := properties.get("$referrer"):
                referring_domain = urlparse(referrer).netloc if referrer != "$direct" else referrer
                referrer_properties = {
                    "$referrer": referrer,
                    "$referring_domain": referring_domain,
                }
                self.register(referrer_properties)
                combined_properties["$set"].update(referrer_properties)
                combined_properties["$referring_domain"] = referring_domain
            combined_properties.update(properties)
        # GeoIP and other person properties on events
        for key, value in {
            PROPERTY_GEOIP_COUNTRY_CODE: self.person.country_code,
            PROPERTY_GEOIP_CITY: self.person.city,
            PROPERTY_GEOIP_REGION: self.person.region,
            PROPERTY_TIMEZONE: self.person.timezone,
            PROPERTY_BROWSER_LANGUAGE: self.person.language,
        }.items():
            combined_properties[key] = value
            combined_properties["$set"][key] = value
        utc_offset = ZoneInfo(self.person.timezone).utcoffset(self.person.cluster.simulation_time)
        combined_properties[PROPERTY_TIMEZONE_OFFSET] = utc_offset.total_seconds() / 60 if utc_offset else 0

        # Saving
        super()._capture_raw(event, combined_properties, distinct_id=self.active_distinct_id)

    def capture_pageview(
        self,
        current_url: str,
        properties: Optional[Properties] = None,
        *,
        referrer: Optional[str] = None,
    ):
        """Capture a $pageview event. $pageleave is handled implicitly."""
        if self.current_url is not None:
            self.capture(EVENT_PAGELEAVE)
        self.person.advance_timer(self.person.cluster.random.uniform(0.02, 0.1))  # A page doesn't load instantly
        self.current_url = current_url
        self.capture(EVENT_PAGEVIEW, properties)

    def identify(self, distinct_id: Optional[str], set_properties: Optional[Properties] = None):
        """Identify person in active client. Similar to JS `posthog.identify()`.

        Use with distinct_id=None for `posthog.people.set()`-like behavior."""
        if set_properties is None:
            set_properties = {}
        identify_properties: Properties = {"$set": set_properties}
        if distinct_id:
            self.is_logged_in = True
            if self.device_id == self.active_distinct_id:
                identify_properties["$anon_distinct_id"] = self.device_id
            identify_properties["$user_id"] = distinct_id
            self.active_distinct_id = distinct_id
        self.capture(EVENT_IDENTIFY, identify_properties)

    def group(
        self,
        group_type: str,
        group_key: str,
        set_properties: Optional[Properties] = None,
    ):
        """Link the person to the specified group. Similar to JS `posthog.group()`."""
        if set_properties is None:
            set_properties = {}
        self.person._groups[group_type] = group_key
        self.person.cluster.matrix._update_group(group_type, group_key, set_properties)
        self.capture(
            EVENT_GROUP_IDENTIFY,
            {
                "$group_type": group_type,
                "$group_key": group_key,
                "$group_set": set_properties,
            },
        )

    def reset(self):
        """Reset active client, for instance when the user logs out. Similar to JS `posthog.reset()`."""
        self.active_distinct_id = self.device_id
        self.is_logged_in = True

    def register(self, super_properties: Properties):
        """Register super properties. Similar to JS `posthog.register()`."""
        self.super_properties.update(super_properties)

    def unregister(self, *super_property_keys: str):
        """Removes super properties. Similar to JS `posthog.unregister()`."""
        for key in super_property_keys:
            self.super_properties.pop(key)


class SimPerson(ABC):
    """A simulation agent, representing an individual person."""

    # Cluster-level metadata
    cluster: "Cluster"
    kernel: bool  # Whether this person is the cluster kernel. Kernels are the most likely to become users
    x: int
    y: int

    # Constant properties
    in_product_id: str  # User ID within the product being simulated (freeform string)
    in_posthog_id: Optional[UUID]  # PostHog person ID (must be a UUID)
    country_code: str
    region: str
    city: str
    timezone: str
    language: str

    # Exposed state - present
    past_events: list[SimEvent]
    future_events: list[SimEvent]

    # Exposed state - at `now`
    distinct_ids_at_now: set[str]
    properties_at_now: Properties
    first_seen_at: Optional[dt.datetime]
    last_seen_at: Optional[dt.datetime]

    # Internal state
    active_client: SimBrowserClient  # Client being used by person
    all_time_pageview_counts: defaultdict[str, int]  # Pageview count per URL across all time
    session_pageview_counts: defaultdict[str, int]  # Pageview count per URL across the ongoing session
    active_session_intent: Optional[SimSessionIntent]
    wake_up_by: dt.datetime
    _groups: dict[str, str]
    _distinct_ids: set[str]
    _properties: Properties

    def __init__(self, *, kernel: bool, cluster: "Cluster", x: int, y: int):
        self.past_events = []
        self.future_events = []
        self.kernel = kernel
        self.cluster = cluster
        self.x = x
        self.y = y
        self.in_product_id = self.cluster.random.randstr(False, 16)
        self.in_posthog_id = None
        self.active_client = SimBrowserClient(self)
        self.country_code = "US"
        self.region = "California"
        self.city = "San Francisco"
        self.timezone = "America/Los_Angeles"
        self.language = "en-US"
        self.all_time_pageview_counts = defaultdict(int)
        self.session_pageview_counts = defaultdict(int)
        self.active_session_intent = None
        self.first_seen_at = None
        self.last_seen_at = None
        self._groups = {}
        self._distinct_ids = set()
        self._properties = {}

    def __str__(self) -> str:
        """Return person ID. Overriding this is recommended but optional."""
        # Sort distinct_ids to ensure deterministic string representation
        return " / ".join(sorted(self._distinct_ids)) if self._distinct_ids else "???"

    def __hash__(self) -> int:
        return hash(self.in_product_id)

    # Helpers

    @property
    def all_events(self) -> Iterable[SimEvent]:
        return chain(self.past_events, self.future_events)

    # Public methods

    def attempt_session(self):
        # If there's no intent, let's skip
        if new_session_intent := self.determine_session_intent():
            self.active_session_intent = new_session_intent
            with self.active_client:
                self.simulate_session()
            # Clean up
            self.session_pageview_counts.clear()
            self.active_session_intent = None
        self.wake_up_by = self.determine_next_session_datetime()

    # Abstract methods

    def decide_feature_flags(self) -> dict[str, Any]:
        """Determine feature flags in force at present."""
        return {}

    @abstractmethod
    def determine_next_session_datetime(self) -> dt.datetime:
        """Intelligently return time of the next session."""
        raise NotImplementedError()

    @abstractmethod
    def determine_session_intent(self) -> Optional[SimSessionIntent]:
        """Determine the session intent for the session that's about to start."""
        raise NotImplementedError()

    @abstractmethod
    def simulate_session(self):
        """Simulate a single session based on current agent state. This is how subclasses can define user behavior."""
        raise NotImplementedError()

    # Cluster state

    def advance_timer(self, seconds: float):
        """Advance simulation time by the given amount of time."""
        self.cluster.advance_timer(seconds)

    def schedule_effect(
        self,
        timestamp: dt.datetime,
        callback: EffectCallback,
        target: Effect.Target,
        *,
        condition: Optional[EffectCondition] = None,
    ):
        """Schedule an effect to apply at a given time.

        An effect is a function that runs on the person, so it can change the person's state."""
        self.cluster.raw_schedule_effect(
            Effect(
                timestamp=timestamp,
                callback=callback,
                source=self,
                target=target,
                condition=condition,
            )
        )

    # Person state

    def set_attribute(self, attr: str, value: Any) -> Literal[True]:
        """Set the person's attribute.

        Useful for defining effects,which are lambdas. Chain them with `and`."""
        setattr(self, attr, value)
        return True

    def move_attribute(self, attr: str, delta: float) -> Literal[True]:
        """Move the person's attribute by the given delta.

        Useful for defining effects, which are lambdas. Chain them with `and`."""
        setattr(self, attr, getattr(self, attr) + delta)
        return True

    def _append_event(
        self,
        event: str,
        properties: Properties,
        *,
        distinct_id: str,
        timestamp: dt.datetime,
    ):
        """Append event to `past_events` or `future_events`, whichever is appropriate."""
        if self.in_posthog_id is None:
            self.in_posthog_id = self.cluster.roll_uuidt()
        if self.first_seen_at is None:
            self.first_seen_at = timestamp
        self.last_seen_at = timestamp
        if self._groups:
            properties["$groups"] = deepcopy(self._groups)
            for group_type, group_key in self._groups.items():
                group_type_index = self.cluster.matrix._get_group_type_index(group_type)
                properties[f"$group_{group_type_index}"] = group_key
                # TODO: Support groups-on-events.
                # This is tricky, because currently there's no way to get the state of a group at _append_event-time.
                # The root of the issue is that groups state is stored on the matrix-level (self.cluster.matrix.groups)
                # - and while time can only go forward at the cluster level, it DOES go backwards at the matrix level,
                # because clusters are simulated one after another.
                # groups_kwargs[f"group{group_type_index}_properties"] = deepcopy(<GROUP_PROPERTIES>)
                # groups_kwargs[f"group{group_type_index}_created_at"] = deepcopy(<GROUP_CREATED_AT>)
        if feature_flags := self.decide_feature_flags():
            for flag_key, flag_value in feature_flags.items():
                properties[f"$feature/{flag_key}"] = flag_value
        sim_event = SimEvent(
            event=event,
            distinct_id=distinct_id,
            properties=properties,
            timestamp=timestamp,
            person_id=self.in_posthog_id,
            person_properties=deepcopy(self._properties),
            person_created_at=self.first_seen_at,
        )
        appropriate_events = self.future_events if sim_event.timestamp > self.cluster.now else self.past_events
        appropriate_events.append(sim_event)
        self._distinct_ids.add(distinct_id)
        if event == EVENT_PAGEVIEW:
            self.all_time_pageview_counts[properties["$current_url"]] += 1
            self.session_pageview_counts[properties["$current_url"]] += 1
        # $set/$set_once processing
        set_properties = properties.get("$set")
        set_once_properties = properties.get("$set_once", {})
        if set_properties:
            for key, value in set_properties.items():
                if key in PROPERTIES_WITH_IMPLICIT_INITIAL_VALUE_TRACKING:
                    set_once_properties[f"$initial_{key.replace('$', '')}"] = value
        if set_once_properties:
            for key, value in set_once_properties.items():
                if key not in self._properties:
                    self._properties[key] = value
        if set_properties:
            self._properties.update(set_properties)
        self.cluster.matrix.distinct_id_to_person[distinct_id] = self

    # Utilities

    def take_snapshot_at_now(self):
        self.distinct_ids_at_now = self._distinct_ids.copy()
        self.properties_at_now = deepcopy(self._properties)

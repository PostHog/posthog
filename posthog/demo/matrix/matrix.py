import uuid
import datetime as dt
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

import mimesis
import tiktoken
import mimesis.random

from posthog.constants import GROUP_TYPES_LIMIT
from posthog.demo.matrix.randomization import PropertiesProvider
from posthog.models import Team, User
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.utils import UUIDT, uuid7

from .models import Effect, SimPerson, SimServerClient


class Cluster(ABC):
    """A cluster of people, e.g. a company, but perhaps a group of friends."""

    MIN_RADIUS: int
    MAX_RADIUS: int

    index: int  # Cluster index
    matrix: "Matrix"  # Parent
    start: dt.datetime  # Start of the simulation
    now: dt.datetime  # Current moment in the simulation
    end: dt.datetime  # End of the simulation (might be same as now or later)

    radius: int
    people_matrix: list[list[SimPerson]]  # Grid containing all people in the cluster

    random: mimesis.random.Random
    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    internet_provider: mimesis.Internet
    datetime_provider: mimesis.Datetime
    finance_provider: mimesis.Finance
    file_provider: mimesis.File

    _simulation_time: dt.datetime
    _reached_now: bool
    _scheduled_effects: deque[Effect]

    def __init__(self, *, index: int, matrix: "Matrix") -> None:
        self.index = index
        self.matrix = matrix
        self.random = matrix.random
        self.properties_provider = matrix.properties_provider
        self.person_provider = matrix.person_provider
        self.numeric_provider = matrix.numeric_provider
        self.address_provider = matrix.address_provider
        self.internet_provider = matrix.internet_provider
        self.datetime_provider = matrix.datetime_provider
        self.finance_provider = matrix.finance_provider
        self.file_provider = matrix.file_provider
        self.start = matrix.start + (matrix.end - matrix.start) * self.initiation_distribution()
        self.now = matrix.now
        self.end = matrix.end
        self.radius = int(self.MIN_RADIUS + self.radius_distribution() * (self.MAX_RADIUS - self.MIN_RADIUS))
        self.people_matrix = [
            [
                matrix.PERSON_CLASS(
                    kernel=(x == self.radius and y == self.radius),
                    x=x,
                    y=y,
                    cluster=self,
                )
                for x in range(1 + self.radius * 2)
            ]
            for y in range(1 + self.radius * 2)
        ]
        self._simulation_time = self.start
        self._reached_now = False
        self._scheduled_effects = deque()

    def __str__(self) -> str:
        """Return cluster ID. Overriding this is recommended but optional."""
        return f"#{self.index + 1}"

    def radius_distribution(self) -> float:
        """Return a value between 0 and 1 signifying where the radius should fall between MIN_RADIUS and MAX_RADIUS."""
        return self.random.uniform(self.MIN_RADIUS, self.MAX_RADIUS)

    def initiation_distribution(self) -> float:
        """Return a value between 0 and 1 determining how far into the overall simulation should this cluster be initiated."""
        return self.random.random()

    def list_neighbors(self, person: SimPerson) -> list[SimPerson]:
        """Return a list of neighbors of a person at (x, y)."""
        x, y = person.x, person.y
        neighbors = []
        for neighbor_x in range(x - 1, x + 2):
            for neighbor_y in range(y - 1, y + 2):
                if (
                    (neighbor_x == x and neighbor_y == y)
                    or not (0 <= neighbor_x < 1 + self.radius * 2)
                    or not (0 <= neighbor_y < 1 + self.radius * 2)
                ):
                    continue
                neighbors.append(self.people_matrix[neighbor_y][neighbor_x])
        return neighbors

    def raw_schedule_effect(self, effect: Effect):
        """Schedule an effect to apply at a given time."""
        for i, existing_effect in enumerate(self._scheduled_effects):
            if existing_effect.timestamp > effect.timestamp:
                self._scheduled_effects.insert(i, effect)
                break
        else:
            self._scheduled_effects.append(effect)

    def advance_timer(self, seconds: float):
        """Advance simulation time by the given amount of time."""
        self.simulation_time += dt.timedelta(seconds=seconds)

    def simulate(self):
        # Initialize people
        for person in self.people:
            person.wake_up_by = person.determine_next_session_datetime()
        while self.simulation_time < self.end:
            # Get next person to simulate
            session_person = min(self.people, key=lambda p: p.wake_up_by)
            self._apply_due_effects(session_person.wake_up_by)
            self.simulation_time = session_person.wake_up_by
            session_person.attempt_session()

    def _apply_due_effects(self, until: dt.datetime):
        while self._scheduled_effects and self._scheduled_effects[0].timestamp <= until:
            effect = self._scheduled_effects.popleft()
            self.simulation_time = effect.timestamp
            resolved_targets: list[SimPerson]
            if effect.target == Effect.Target.SELF:
                resolved_targets = [effect.source]
            elif effect.target == Effect.Target.ALL_NEIGHBORS:
                resolved_targets = self.list_neighbors(effect.source)
            elif effect.target == Effect.Target.RANDOM_NEIGHBOR:
                resolved_targets = [self.random.choice(self.list_neighbors(effect.source))]
            else:
                raise ValueError(f"Unknown effect target {effect.target}")
            for target in resolved_targets:
                if not effect.condition or effect.condition(target):
                    effect.callback(target)

    @property
    def people(self) -> list[SimPerson]:
        # Return deterministically ordered list to ensure consistent random number sequence consumption.
        return [person for row in self.people_matrix for person in row]

    @property
    def kernel(self) -> SimPerson:
        return self.people_matrix[self.radius][self.radius]

    @property
    def simulation_time(self) -> dt.datetime:
        return self._simulation_time

    @simulation_time.setter
    def simulation_time(self, value: dt.datetime):
        if value < self._simulation_time:
            return  # Can't turn time back
        self._simulation_time = value
        if not self._reached_now and self._simulation_time >= self.now:
            # If we've just reached matrix's `now`, take a snapshot of the current state
            # for dividing past and future events
            self._reached_now = True
            for person in self.people:
                person.take_snapshot_at_now()

    # Utilities

    def roll_uuidt(self, at_timestamp: Optional[dt.datetime] = None) -> UUIDT:
        if at_timestamp is None:
            at_timestamp = self.simulation_time
        return UUIDT(int(at_timestamp.timestamp() * 1000), seeded_random=self.random)

    def roll_uuid_v7(self, at_timestamp: Optional[dt.datetime] = None) -> uuid.UUID:
        if at_timestamp is None:
            at_timestamp = self.simulation_time
        return uuid7(int(at_timestamp.timestamp() * 1000), random=self.random)


class Matrix(ABC):
    """The top level of a demo data simulation.

    Structure:
    - Matrix
        - n_clusters * Cluster
            - (Cluster.radius * 2 + 1)^2 * SimPerson
                - x * SimBrowserClient (x being locked at 1 currently)
                - y * SimEvent
    """

    PRODUCT_NAME: str
    CLUSTER_CLASS: type[Cluster]
    PERSON_CLASS: type[SimPerson]

    start: dt.datetime
    now: dt.datetime
    end: dt.datetime
    group_type_index_offset: int
    # A mapping of groups. The first key is the group type, the second key is the group key.
    groups: defaultdict[str, defaultdict[str, dict[str, Any]]]
    distinct_id_to_person: dict[str, SimPerson]
    clusters: list[Cluster]
    is_complete: Optional[bool]
    server_client: SimServerClient

    random: mimesis.random.Random
    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    internet_provider: mimesis.Internet
    datetime_provider: mimesis.Datetime
    finance_provider: mimesis.Finance
    file_provider: mimesis.File
    gpt_4o_encoding: tiktoken.Encoding

    def __init__(
        self,
        seed: Optional[str] = None,
        *,
        now: Optional[dt.datetime] = None,
        days_past: int = 180,
        days_future: int = 30,
        n_clusters: int = settings.DEMO_MATRIX_N_CLUSTERS,
        group_type_index_offset: int = 0,
    ):
        if now is None:
            now = timezone.now()
        self.now = now
        self.start = (now - dt.timedelta(days=days_past)).replace(hour=0, minute=0, second=0, microsecond=0)
        self.end = (now + dt.timedelta(days=days_future)).replace(hour=0, minute=0, second=0, microsecond=0)
        self.group_type_index_offset = group_type_index_offset
        # We initialize random data providers here and pass it down as a performance measure
        # Provider initialization is a bit intensive, as it loads some JSON data,
        # so doing it at cluster or person level could be overly taxing
        self.random = mimesis.random.Random(seed)
        self.properties_provider = PropertiesProvider(seed=seed)
        self.person_provider = mimesis.Person(seed=seed)
        self.numeric_provider = mimesis.Numeric(seed=seed)
        self.address_provider = mimesis.Address(seed=seed)
        self.internet_provider = mimesis.Internet(seed=seed)
        self.datetime_provider = mimesis.Datetime(seed=seed)
        self.finance_provider = mimesis.Finance(seed=seed)
        self.file_provider = mimesis.File(seed=seed)
        self.groups = defaultdict(lambda: defaultdict(dict))
        self.distinct_id_to_person = {}
        self.clusters = [self.CLUSTER_CLASS(index=i, matrix=self) for i in range(n_clusters)]
        self.server_client = SimServerClient(self)
        self.gpt_4o_encoding = tiktoken.encoding_for_model("gpt-4o")
        self.is_complete = None

    @property
    def people(self) -> list[SimPerson]:
        return [person for cluster in self.clusters for person in cluster.people]

    @abstractmethod
    def set_project_up(self, team: Team, user: User):
        """Project setup, such as relevant insights, dashboards, feature flags, etc."""
        team.name = self.PRODUCT_NAME
        FeatureFlag.objects.create(
            team=team,
            key="llm-observability",
            name="Breaking the fourth wall: PostHog's LLM analytics flag.",
            filters={"groups": [{"variant": None, "properties": [], "rollout_percentage": 100}]},
            created_by=user,
            created_at=dt.datetime.fromtimestamp(0),  # Epoch
        )

    def simulate(self):
        if self.is_complete is not None:
            raise RuntimeError("Simulation can only be started once!")
        self.is_complete = False
        for cluster in self.clusters:
            cluster.simulate()
        self.is_complete = True

    def _update_group(self, group_type: str, group_key: str, set_properties: dict[str, Any]):
        if len(self.groups) == GROUP_TYPES_LIMIT and group_type not in self.groups:
            raise Exception(f"Cannot add group type {group_type} to simulation, limit of {GROUP_TYPES_LIMIT} reached!")
        self.groups[group_type][group_key].update(set_properties)

    def _get_group_type_index(self, group_type: str) -> Optional[int]:
        try:
            return list(self.groups.keys()).index(group_type) + self.group_type_index_offset
        except ValueError:
            return None

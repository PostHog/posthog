from abc import ABC, abstractmethod
from collections import defaultdict
from typing import (
    Any,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Type,
)

import mimesis
import mimesis.random
from django.conf import settings
from django.utils import timezone

from posthog.constants import GROUP_TYPES_LIMIT
from posthog.demo.matrix.randomization import PropertiesProvider
from posthog.models import Team, User

from .models import SimPerson


class Cluster(ABC):
    """A cluster of people, e.g. a company, but perhaps a group of friends."""

    index: int  # Cluster index
    matrix: "Matrix"  # Parent
    start: timezone.datetime  # Start of the simulation
    end: timezone.datetime  # End of the simulation

    radius: int
    # Grid containing all people in the cluster.
    people_matrix: List[List[SimPerson]]

    random: mimesis.random.Random
    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    internet_provider: mimesis.Internet
    datetime_provider: mimesis.Datetime
    finance_provider: mimesis.Finance
    file_provider: mimesis.File

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
        self.start = matrix.start + (matrix.end - matrix.start) * self._initation_distribution()
        self.end = matrix.end
        self.radius = self._radius_distribution()
        self.people_matrix = [
            [
                matrix.person_model(kernel=(x == self.radius and y == self.radius), x=x, y=y, cluster=self,)
                for x in range(1 + self.radius * 2)
            ]
            for y in range(1 + self.radius * 2)
        ]

    def __str__(self) -> str:
        """Return cluster ID. Overriding this is recommended but optional."""
        return str(self.index + 1)

    @abstractmethod
    def _radius_distribution(self) -> int:
        """Return a pseudo-random radius, based on a chosen statistical distribution."""

    @abstractmethod
    def _initation_distribution(self) -> float:
        """Return a pseudo-random value between 0 and 1 determining how far into the overall simulation should this cluster be initiated."""

    def _list_neighbors(self, x: int, y: int) -> List[SimPerson]:
        """Return a list of neighbors of a person at (x, y)."""
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

    def simulate(self):
        person = self.people_matrix[self.radius][self.radius]
        person.simulate()
        if settings.DEBUG:
            self._print_simulation_update(0, person)
        # Simulate in a spiral developing outwards from the center
        for distance_from_kernel in range(1, self.radius + 1):
            cursor_x_y = [self.radius - distance_from_kernel, self.radius - distance_from_kernel]
            for side in range(4):
                for index_within_side in range(distance_from_kernel * 2):
                    person = self.people_matrix[cursor_x_y[1]][cursor_x_y[0]]
                    person.simulate()
                    step = 1 if side < 2 else -1  # Increment coordinate for sides 0 and 1, decrement for sides 2 and 3
                    cursor_x_y[
                        0 if side % 2 == 0 else 1
                    ] += step  # Move in X axis for sides 0 and 2, Y axis for sides 1 and 3
                    if settings.DEBUG:
                        inner_population = (distance_from_kernel * 2 - 1) ** 2
                        person_spiral_index = inner_population + index_within_side + side * distance_from_kernel * 2
                        self._print_simulation_update(person_spiral_index, person)

    def _print_simulation_update(self, person_spiral_index: int, person: SimPerson):
        print(
            f"Simulated person {person_spiral_index + 1} in cluster {self} ({len(person.events)} event{'' if len(person.events) == 1 else 's'}):"
        )
        for person_row in self.people_matrix:
            print(" ".join(("X" if hasattr(person, "_simulation_time") else "-" for person in person_row)))

    @property
    def people(self) -> List[SimPerson]:
        return [person for row in self.people_matrix for person in row]


class Matrix(ABC):
    person_model: Type[SimPerson]
    cluster_model: Type[Cluster]

    event_names: Set[str]
    property_names: Set[str]
    event_property_pairs: Set[Tuple[str, str]]

    start: timezone.datetime
    end: timezone.datetime
    # A mapping of groups. The first key is the group type, the second key is the group key.
    groups: DefaultDict[str, DefaultDict[str, Dict[str, Any]]]
    clusters: List[Cluster]
    simulation_complete: Optional[bool]

    random: mimesis.random.Random
    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    internet_provider: mimesis.Internet
    datetime_provider: mimesis.Datetime
    finance_provider: mimesis.Finance
    file_provider: mimesis.File

    def __init__(
        self, seed: Optional[str] = None, *, start: timezone.datetime, end: timezone.datetime, n_clusters: int,
    ):
        self.start = start
        self.end = end
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
        self.clusters = [self.cluster_model(index=i, matrix=self) for i in range(n_clusters)]
        self.simulation_complete = None
        self.event_names = set()
        self.property_names = set()
        self.event_property_pairs = set()

    @abstractmethod
    def set_project_up(self, team: Team, user: User):
        """Project setup, such as relevant insights, dashboards, feature flags, etc."""

    def simulate(self):
        if self.simulation_complete is not None:
            raise RuntimeError("Simulation can only be started once!")
        self.simulation_complete = False
        for cluster in self.clusters:
            cluster.simulate()
        self.simulation_complete = True

    def update_group(self, group_type: str, group_key: str, set_properties: Dict[str, Any]):
        if len(self.groups) == GROUP_TYPES_LIMIT and group_type not in self.groups:
            raise Exception(f"Cannot add group type {group_type} to simulation, limit of {GROUP_TYPES_LIMIT} reached!")
        self.groups[group_type][group_key].update(set_properties)

    def register_event_schema(self, event: str, properties: Iterable[str]):
        self.event_names.add(event)
        for property_name in properties:
            self.property_names.add(property_name)
            self.event_property_pairs.add((event, property_name))

    @property
    def people(self) -> List[SimPerson]:
        return [person for cluster in self.clusters for person in cluster.people]

import datetime as dt
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List, Optional, Type

import mimesis
import mimesis.random
from django.conf import settings

from posthog.constants import GROUP_TYPES_LIMIT
from posthog.demo.matrix.randomization import PropertiesProvider
from posthog.models import Team, User

from .models import SimPerson


class Cluster(ABC):
    """A cluster of people, e.g. a company, but perhaps a group of friends."""

    index: int  # Cluster index
    start: dt.datetime  # Start of the simulation
    end: dt.datetime  # End of the simulation

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

    update_group: Callable[[str, str, Dict[str, Any]], None]

    def __init__(
        self,
        *,
        index: int,
        start: dt.datetime,
        end: dt.datetime,
        person_model: Type[SimPerson],
        random: mimesis.random.Random,
        properties_provider: PropertiesProvider,
        person_provider: mimesis.Person,
        numeric_provider: mimesis.Numeric,
        address_provider: mimesis.Address,
        internet_provider: mimesis.Internet,
        datetime_provider: mimesis.Datetime,
        finance_provider: mimesis.Finance,
        update_group: Callable[[str, str, Dict[str, Any]], None],
    ) -> None:
        self.index = index
        self.start = start
        self.end = end
        self.random = random
        self.properties_provider = properties_provider
        self.person_provider = person_provider
        self.numeric_provider = numeric_provider
        self.address_provider = address_provider
        self.internet_provider = internet_provider
        self.datetime_provider = datetime_provider
        self.finance_provider = finance_provider
        self.radius = self.radius_distribution()
        self.people_matrix = [
            [
                person_model(kernel=(x == self.radius and y == self.radius), cluster=self, update_group=update_group)
                for x in range(1 + self.radius * 2)
            ]
            for y in range(1 + self.radius * 2)
        ]
        self.update_group = update_group

    def __str__(self) -> str:
        """Return cluster ID. Overriding this is recommended but optional."""
        return str(self.index + 1)

    @abstractmethod
    def radius_distribution(self) -> int:
        """Return a pseudo-random radius, based on a chosen statistical distribution."""

    def simulate(self):
        person = self.people_matrix[self.radius][self.radius]
        person.simulate()
        if settings.DEBUG:
            self._print_simulation_update(0, person)
        # Simulate in a spiral developing outwards from the center
        for distance_from_kernel in range(1, self.radius + 1):
            cursor_x_y = [self.radius - distance_from_kernel, self.radius - distance_from_kernel]
            for side in range(4):
                for sub_index in range(distance_from_kernel * 2):
                    person = self.people_matrix[cursor_x_y[1]][cursor_x_y[0]]
                    person.simulate()
                    person_spiral_index = (
                        sub_index + side * distance_from_kernel * 2 + ((distance_from_kernel * 2 - 1) ** 2)
                    )
                    step = 1 if side < 2 else -1  # Increment coordinate for sides 0 and 1, decrement for sides 2 and 3
                    cursor_x_y[
                        0 if side % 2 == 0 else 1
                    ] += step  # Move in X axis for sides 0 and 2, Y axis for sides 1 and 3
                    if settings.DEBUG:
                        self._print_simulation_update(person_spiral_index, person)

    def _print_simulation_update(self, person_spiral_index: int, person: SimPerson):
        print(
            f"Simulated person {person_spiral_index + 1} in cluster {self} ({len(person.events)} event{'' if len(person.events) == 1 else 's'}):"
        )
        for person_row in self.people_matrix:
            print(" ".join(("X" if hasattr(person, "simulation_time") else "-" for person in person_row)))

    @property
    def people(self) -> List[SimPerson]:
        return [person for row in self.people_matrix for person in row]


class Matrix(ABC):
    person_model: Type[SimPerson]
    cluster_model: Type[Cluster] = Cluster

    start: dt.datetime
    end: dt.datetime
    # A mapping of groups. The first key is the group type, the second key is the group key.
    groups: DefaultDict[str, DefaultDict[str, Dict[str, Any]]]
    clusters: List[Cluster]

    random: mimesis.random.Random
    properties_provider: PropertiesProvider
    person_provider: mimesis.Person
    numeric_provider: mimesis.Numeric
    address_provider: mimesis.Address
    internet_provider: mimesis.Internet
    datetime_provider: mimesis.Datetime
    finance_provider: mimesis.Finance

    def __init__(
        self, seed: Optional[str] = None, *, start: dt.datetime, end: dt.datetime, n_clusters: int,
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
        self.groups_mapping = defaultdict(lambda: defaultdict(dict))
        self.clusters = [
            self.cluster_model(
                index=i,
                start=start,
                end=end,
                person_model=self.person_model,
                random=self.random,
                properties_provider=self.properties_provider,
                person_provider=self.person_provider,
                numeric_provider=self.numeric_provider,
                address_provider=self.address_provider,
                internet_provider=self.internet_provider,
                datetime_provider=self.datetime_provider,
                finance_provider=self.finance_provider,
                update_group=self.update_group,
            )
            for i in range(n_clusters)
        ]

    @abstractmethod
    def set_project_up(self, team: Team, user: User):
        """Project setup, such as relevant insights, dashboards, feature flags, etc."""

    def simulate(self):
        for cluster in self.clusters:
            cluster.simulate()

    def update_group(self, group_type: str, group_key: str, set_properties: Dict[str, Any]):
        if len(self.groups) == GROUP_TYPES_LIMIT and group_type not in self.groups:
            raise Exception(f"Cannot add group type {group_type} to simulation, limit of {GROUP_TYPES_LIMIT} reached!")
        self.groups[group_type][group_key].update(set_properties)

    @property
    def people(self) -> List[SimPerson]:
        return [person for cluster in self.clusters for person in cluster.people]

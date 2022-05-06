import datetime as dt
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional, Type

from posthog.models import Team, User

from .models import SimGroup, SimPerson

# Event name constants to be used in simulations
EVENT_PAGEVIEW = "$pageview"
EVENT_AUTOCAPTURE = "$autocapture"


class Cluster:
    """A cluster of people."""

    min_radius: int = 0
    max_radius: int = 4

    start: dt.datetime
    end: dt.datetime

    radius: int
    # Grid containing all people in the cluster.
    people_matrix: List[List[SimPerson]]
    # A mapping of groups. The first key is the group type, the second key is the group key.
    groups_mapping: DefaultDict[str, Dict[str, SimGroup]]

    def __init__(
        self, seed: Optional[str] = None, *, start: dt.datetime, end: dt.datetime, person_model: Type[SimPerson]
    ) -> None:
        random.seed(seed)
        self.start = start
        self.end = end
        self.radius = random.randint(self.min_radius, self.max_radius)
        self.people_matrix = [[person_model() for _ in range(1 + self.radius * 2)] for _ in range(1 + self.radius * 2)]
        self.groups_mapping = defaultdict(dict)

    def simulate(self):
        self.people_matrix[self.radius][self.radius].simulate(start=self.start, end=self.end)
        # TODO: Support neighbors
        # for distance_from_kernel in range(1, self.radius + 1):

    @property
    def people(self) -> List[SimPerson]:
        return [person for row in self.people_matrix for person in row]

    @property
    def groups(self) -> List[SimGroup]:
        return [group for groups_of_type in self.groups_mapping.values() for group in groups_of_type.values()]


class Matrix(ABC):
    person_model: Type[SimPerson]

    start: dt.datetime
    end: dt.datetime
    clusters: List[Cluster]

    def __init__(
        self, seed: Optional[str] = None, *, start: dt.datetime, end: dt.datetime, n_clusters: int,
    ):
        self.start = start
        self.end = end
        self.clusters = [Cluster(seed, start=start, end=end, person_model=self.person_model) for _ in range(n_clusters)]

    def simulate(self):
        for cluster in self.clusters:
            cluster.simulate()

    @property
    def people(self) -> List[SimPerson]:
        return [person for cluster in self.clusters for person in cluster.people]

    @property
    def groups(self) -> List[SimGroup]:
        return [group for cluster in self.clusters for group in cluster.groups]

    @abstractmethod
    def set_project_up(self, team: Team, user: User):
        """Project setup, such as relevant insights, dashboards, feature flags, etc."""
        raise NotImplementedError

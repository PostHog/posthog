import datetime as dt
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import DefaultDict, Dict, List, Type

from posthog.models import Team, User

from .models import SimGroup, SimPerson


class Cluster:
    """A cluster of people."""

    start: dt.datetime
    end: dt.datetime
    # Grid containing all people in the cluster.
    people_matrix: List[List[SimPerson]]
    # A mapping of groups. The first key is the group type, the second key is the group key.
    groups_mapping: DefaultDict[str, Dict[str, SimGroup]]

    def __init__(
        self, *, start: dt.datetime, end: dt.datetime, min_radius: int, max_radius: int, person_model: Type[SimPerson],
    ) -> None:
        self.start = start
        self.end = end
        radius = random.randint(min_radius, max_radius)
        self.people_matrix = [[person_model() for _ in range(1 + radius * 2)] for _ in range(1 + radius * 2)]
        self.groups_mapping = defaultdict(dict)

    def simulate(self):
        raise NotImplementedError

    @property
    def people(self) -> List[SimPerson]:
        return [person for row in self.people_matrix for person in row]

    @property
    def groups(self) -> List[SimGroup]:
        return [group for groups_of_type in self.groups_mapping.values() for group in groups_of_type.values()]


class Matrix(ABC):
    start: dt.datetime
    end: dt.datetime
    clusters: List[Cluster]

    def __init__(
        self, *, start: dt.datetime, end: dt.datetime, n_clusters: int,
    ):
        self.start = start
        self.end = end
        self.clusters = [self.make_cluster() for _ in range(n_clusters)]

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
    def make_cluster() -> Cluster:
        raise NotImplementedError

    @abstractmethod
    def set_project_up(self, team: Team, user: User):
        """Project setup, such as relevant insights, dashboards, feature flags, etc."""
        raise NotImplementedError

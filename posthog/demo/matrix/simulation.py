import datetime as dt
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Callable, DefaultDict, Dict, List, Optional, Tuple, Type

from posthog.models import Team, User

from .models import Effect, SimEvent, SimGroup, SimPerson, SimSnapshot


class Cluster:
    """A cluster of people."""

    start: dt.datetime
    end: dt.datetime
    # Grid containing all people in the cluster. It wraps around at the edges.
    people_matrix: List[List[SimPerson]]
    # A mapping of groups. The first key is the group type, the second key is the group key.
    groups_mapping: DefaultDict[str, Dict[str, SimGroup]]

    def __init__(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        min_root_size: int,
        max_root_size: int,
        person_model: Type[SimPerson],
    ) -> None:
        self.start = start
        self.end = end
        width = random.randint(min_root_size, max_root_size)
        height = random.randint(min_root_size, max_root_size)
        self.people_matrix = [[person_model() for _ in range(width)] for _ in range(height)]
        self.groups_mapping = defaultdict(dict)

    def simulate(self):
        point_in_time = self.start
        effects: List[Effect] = []
        sessions_generators = [person.sessions(point_in_time) for person in self.people]
        for sessions_generator in sessions_generators:
            for session in sessions_generator:
                pass  # We don't care about the result YET

    def determine_neighbors(self, origin: Tuple[int, int], target_offset: Optional[Tuple[int, int]]) -> List[SimPerson]:
        """Determine the neighbor of the origin person. Wraps around the edges of the matrix.
        If a target offset is specified, only the neighbor at that offset will be returned.
        Otherwise, all 8 neighbors will be returned.
        """
        max_x, max_y = len(self.people_matrix[0]) - 1, len(self.people_matrix) - 1
        if target_offset is not None:
            offsets = [target_offset]
        else:
            offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        neighbors: List[SimPerson] = []
        for offset in offsets:
            absolute_x = (origin[0] + offset[0]) % max_x
            absolute_y = (origin[1] + offset[1]) % max_y
            neighbors.append(self.people_matrix[absolute_y][absolute_x])
        return neighbors

    @property
    def people(self) -> List[SimPerson]:
        return [person for row in self.people_matrix for person in row]

    @property
    def groups(self) -> List[SimGroup]:
        return [group for groups_of_type in self.groups_mapping.values() for group in groups_of_type.values()]


class Matrix(ABC):
    """The Matrix, where people go on with their lives."""

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
        """Project setup, such as relevant insights, dashboards, feature flags, etc. """
        pass

import datetime as dt
from abc import ABC, abstractmethod
from typing import List

from posthog.models import Team, User

from .models import SimGroup, SimPerson


class Matrix(ABC):
    start: dt.datetime
    end: dt.datetime

    def __init__(
        self, *, start: dt.datetime, end: dt.datetime, n_clusters: int,
    ):
        self.start = start
        self.end = end

    def simulate(self):
        pass

    @property
    def people(self) -> List[SimPerson]:
        return []

    @property
    def groups(self) -> List[SimGroup]:
        return []

    @abstractmethod
    def set_project_up(self, team: Team, user: User):
        """Project setup, such as relevant insights, dashboards, feature flags, etc. """
        pass

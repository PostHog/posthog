import datetime as dt

from .matrix.matrix import Matrix
from .matrix.models import SimPerson

# Event name constants
EVENT_SIGNUP = "signup"


class HedgeboxPerson(SimPerson):
    def simulate(self, *, start: dt.datetime, end: dt.datetime):
        self.capture_event(EVENT_SIGNUP, start)


class HedgeboxMatrix(Matrix):
    person_model = HedgeboxPerson

    def set_project_up(self, team, user):
        pass


# x x x x x
# x x x x x
# x x x x x
# x x x x x
# x x x x x

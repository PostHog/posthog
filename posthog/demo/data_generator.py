from typing import Dict, List

from posthog.ee import is_clickhouse_enabled
from posthog.models import Action, Event, Person, PersonDistinctId, Team
from posthog.models.session_recording_event import SessionRecordingEvent
from posthog.models.utils import UUIDT


class DataGenerator:
    def __init__(self, team: Team, n_days=14, n_people=100):
        self.team = team
        self.n_days = n_days
        self.n_people = n_people
        self.events: List[Dict] = []
        self.snapshots: List[Dict] = []
        self.distinct_ids: List[str] = []

    def create(self, dashboards=True):
        self.create_missing_events_and_properties()
        self.create_people()

        for index, (person, distinct_id) in enumerate(zip(self.people, self.distinct_ids)):
            self.populate_person_events(person, distinct_id, index)
            self.populate_session_recording(person, distinct_id, index)

        self.bulk_import_events()
        if dashboards:
            self.create_actions_dashboards()
        self.team.save()
        _recalculate(team=self.team)

    def create_people(self):
        self.people = [self.make_person(i) for i in range(self.n_people)]
        self.distinct_ids = [str(UUIDT()) for _ in self.people]
        Person.objects.bulk_create(self.people)

        pids = [
            PersonDistinctId(team=self.team, person=person, distinct_id=distinct_id)
            for person, distinct_id in zip(self.people, self.distinct_ids)
        ]
        PersonDistinctId.objects.bulk_create(pids)
        if is_clickhouse_enabled():
            from ee.clickhouse.models.person import create_person, create_person_distinct_id

            for person in self.people:
                create_person(team_id=person.team.pk, properties=person.properties, is_identified=person.is_identified)
            for pid in pids:
                create_person_distinct_id(pid.team.pk, pid.distinct_id, str(pid.person.uuid))  # use dummy number for id

    def make_person(self, index):
        return Person(team=self.team, properties={"is_demo": True})

    def create_missing_events_and_properties(self):
        raise NotImplementedError("You need to implement create_missing_events_and_properties")

    def create_actions_dashboards(self):
        raise NotImplementedError("You need to implement create_actions_dashboards")

    def populate_person_events(self, person: Person, distinct_id: str, _index: int):
        raise NotImplementedError("You need to implement populate_person_events")

    def populate_session_recording(self, person: Person, distinct_id: str, index: int):
        pass

    def bulk_import_events(self):
        if is_clickhouse_enabled():
            from ee.clickhouse.demo import bulk_create_events, bulk_create_session_recording_events

            bulk_create_events(self.events, team=self.team)
            bulk_create_session_recording_events(self.snapshots, team_id=self.team.pk)
        else:
            Event.objects.bulk_create([Event(**kw, team=self.team) for kw in self.events])
            SessionRecordingEvent.objects.bulk_create(
                [SessionRecordingEvent(**kw, team=self.team) for kw in self.snapshots]
            )

    def add_if_not_contained(self, array, value):
        if value not in array:
            array.append(value)

    def add_event(self, **kw):
        self.events.append(kw)


def _recalculate(team: Team) -> None:
    actions = Action.objects.filter(team=team)
    for action in actions:
        action.calculate_events()

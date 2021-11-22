from typing import Dict, List, Optional
from uuid import uuid4

from django.utils import timezone

from posthog.models import Action, Event, Group, Person, PersonDistinctId, Team
from posthog.models.session_recording_event import SessionRecordingEvent
from posthog.models.utils import UUIDT
from posthog.utils import is_clickhouse_enabled


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
        self.create_groups()

        for index, (person, distinct_id) in enumerate(zip(self.people, self.distinct_ids)):
            groups = self.group_combinations[0]
            self.populate_person_events(person, distinct_id, index, groups)
            self.populate_session_recording(person, distinct_id, index)

        self.bulk_import_events()
        if dashboards:
            self.create_actions_dashboards()
        self.team.save()
        _recalculate(team=self.team)

    def create_people(self):
        from posthog.api.capture import capture_internal

        self.people = [self.make_person(i) for i in range(self.n_people)]
        self.distinct_ids = [str(UUIDT()) for _ in self.people]
        now = timezone.now()

        for person, distinct_id in zip(self.people, self.distinct_ids):

            email = person.properties.get("email", None)
            properties = {"$set": person.properties}

            if email:
                properties.update({"distinct_id": email, "$anon_distinct_id": distinct_id})
            else:
                properties.update({"distinct_id": distinct_id})
            capture_internal(
                event={"event": "$identify", "properties": properties},
                distinct_id=distinct_id,
                ip=None,
                site_url=None,
                now=now,
                sent_at=now,
                team_id=self.team.pk,
                event_uuid=uuid4(),
            )

    def make_person(self, index):
        return Person(team=self.team, properties={"is_demo": True})

    def create_missing_events_and_properties(self):
        raise NotImplementedError("You need to implement create_missing_events_and_properties")

    def create_actions_dashboards(self):
        raise NotImplementedError("You need to implement create_actions_dashboards")

    def populate_person_events(self, person: Person, distinct_id: str, _index: int, groups: Optional[Dict] = None):
        raise NotImplementedError("You need to implement populate_person_events")

    def populate_session_recording(self, person: Person, distinct_id: str, index: int):
        pass

    def create_groups(self):
        from posthog.api.capture import capture_internal

        groups = [
            {"$group_key": "project:1", "$group_type": "project", "$group_set": {"size": 20}},
            {"$group_key": "project:2", "$group_type": "project", "$group_set": {"size": 20}},
            {"$group_key": "organization:1", "$group_type": "organization", "$group_set": {"players": 5}},
        ]

        now = timezone.now()

        for group in groups:
            capture_internal(
                event={"event": "$groupidentify", "properties": group},
                distinct_id="dummyId",
                ip=None,
                site_url=None,
                now=now,
                sent_at=now,
                team_id=self.team.pk,
                event_uuid=uuid4(),
            )

        self.group_combinations = [
            {"project": "project:1"},
            {"project": "project:2"},
            {"organization": "organization:1"},
            {"project": "project:2", "organization": "organization:1"},
        ]

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

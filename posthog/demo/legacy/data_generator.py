import json
from uuid import uuid4

from django.conf import settings

import psycopg2
from psycopg2.extras import execute_values

from posthog.demo.matrix.persons_db_sync import _get_persons_db_url
from posthog.models import Person, Team
from posthog.models.utils import UUIDT
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class DataGenerator:
    def __init__(self, team: Team, n_days=14, n_people=100):
        self.team = team
        self.n_days = n_days
        self.n_people = n_people
        self.events: list[dict] = []
        self.snapshots: list[dict] = []
        self.distinct_ids: list[str] = []

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

    def create_people(self):
        self.people = [self.make_person(i) for i in range(self.n_people)]
        self.distinct_ids = [str(UUIDT()) for _ in self.people]

        person_table_name = settings.PERSON_TABLE_NAME
        persons_db_url = _get_persons_db_url()

        person_rows = [
            (
                self.team.pk,
                str(person.uuid),
                json.dumps(person.properties),
                person.is_identified,
            )
            for person in self.people
        ]

        with psycopg2.connect(persons_db_url) as conn:
            with conn.cursor() as cur:
                results = execute_values(
                    cur,
                    f"""
                    INSERT INTO {person_table_name} (team_id, uuid, properties, is_identified)
                    VALUES %s
                    RETURNING id, uuid
                    """,
                    person_rows,
                    fetch=True,
                )
                uuid_to_pk = {str(uuid): pk for pk, uuid in results}
                for person in self.people:
                    person.pk = uuid_to_pk[str(person.uuid)]

                distinct_id_rows = [
                    (self.team.pk, distinct_id, person.pk, 0)
                    for person, distinct_id in zip(self.people, self.distinct_ids)
                ]
                execute_values(
                    cur,
                    """
                    INSERT INTO posthog_persondistinctid (team_id, distinct_id, person_id, version)
                    VALUES %s
                    """,
                    distinct_id_rows,
                )

        from posthog.models.person.util import create_person, create_person_distinct_id

        for person in self.people:
            create_person(
                uuid=str(person.uuid),
                team_id=person.team.pk,
                properties=person.properties,
                is_identified=person.is_identified,
                version=0,
            )
        for person, distinct_id in zip(self.people, self.distinct_ids):
            create_person_distinct_id(person.team.pk, distinct_id, str(person.uuid))

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
        from posthog.models.event.util import create_event

        for event_data in self.events:
            create_event(**event_data, team=self.team, event_uuid=uuid4())
        for data in self.snapshots:
            timestamp = data["timestamp"]
            distinct_id = data["distinct_id"]
            session_id = data["session_id"]
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=distinct_id,
                first_timestamp=timestamp,
                last_timestamp=timestamp,
                ensure_analytics_event_in_session=False,
            )

    def add_if_not_contained(self, array, value):
        if value not in array:
            array.append(value)

    def add_event(self, **kw):
        self.events.append(kw)

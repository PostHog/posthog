from uuid import UUID, uuid4

from posthog.client import sync_execute
from posthog.models import Team
from posthog.models.cohort.util import insert_static_cohort
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.team.util import delete_teams_clickhouse_data
from posthog.test.base import BaseTest, ClickhouseDestroyTablesMixin, ClickhouseTestMixin, _create_event


class TestDeleteEvents(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.teams = [
            self.team,
            Team.objects.create(organization=self.organization),
            Team.objects.create(organization=self.organization),
        ]

    def test_delete_events(self):
        _create_event(event_uuid=uuid4(), event="event1", team=self.teams[0], distinct_id="1")
        _create_event(event_uuid=uuid4(), event="event2", team=self.teams[1], distinct_id="2")
        _create_event(event_uuid=uuid4(), event="event3", team=self.teams[2], distinct_id="3")

        delete_teams_clickhouse_data([self.teams[0].pk, self.teams[1].pk])
        self.assertEqual(self.select_remaining("events", "event"), ["event3"])

    def test_delete_persons(self):
        uuid0 = create_person(team_id=self.teams[0].pk, properties={"x": 0}, version=0)
        uuid1 = create_person(team_id=self.teams[1].pk, properties={"x": 1}, version=0)
        uuid2 = create_person(team_id=self.teams[2].pk, properties={"x": 2}, version=0)
        create_person_distinct_id(self.teams[0].pk, "0", uuid0)
        create_person_distinct_id(self.teams[1].pk, "1", uuid1)
        create_person_distinct_id(self.teams[2].pk, "2", uuid2)

        delete_teams_clickhouse_data([self.teams[0].pk, self.teams[1].pk])

        self.assertEqual(self.select_remaining("person", "properties"), ['{"x": 2}'])
        self.assertEqual(self.select_remaining("person_distinct_id", "distinct_id"), ["2"])

    def test_delete_cohorts(self):
        insert_static_cohort([uuid4()], 0, self.teams[0])
        insert_static_cohort([uuid4()], 1, self.teams[1])
        insert_static_cohort([uuid4()], 2, self.teams[2])

        self._insert_cohortpeople_row(self.teams[0], uuid4(), 3)
        self._insert_cohortpeople_row(self.teams[1], uuid4(), 4)
        self._insert_cohortpeople_row(self.teams[2], uuid4(), 5)

        delete_teams_clickhouse_data([self.teams[0].pk, self.teams[1].pk])

        self.assertEqual(self.select_remaining("person_static_cohort", "cohort_id"), [2])
        self.assertEqual(self.select_remaining("cohortpeople", "cohort_id"), [5])

    def select_remaining(self, table, column):
        ids = [team.pk for team in self.teams]
        rows = sync_execute(f"SELECT {column} FROM {table} WHERE team_id IN %(ids)s", {"ids": ids})
        return [row[0] for row in rows]

    def _insert_cohortpeople_row(self, team: Team, person_id: UUID, cohort_id: int):
        sync_execute(
            f"""
            INSERT INTO cohortpeople (person_id, cohort_id, team_id, sign)
            VALUES (%(person_id)s, %(cohort_id)s, %(team_id)s, 1)
        """,
            {"person_id": str(person_id), "cohort_id": cohort_id, "team_id": team.pk},
        )

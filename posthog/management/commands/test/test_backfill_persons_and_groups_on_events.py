from time import sleep
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.management.commands.backfill_persons_and_groups_on_events import run_backfill
from posthog.models.event.sql import EVENTS_DATA_TABLE


def create_test_events(properties=""):
    sync_execute(
        f"""
        INSERT INTO {EVENTS_DATA_TABLE()} (event, team_id, uuid, timestamp, distinct_id, properties)
        VALUES
            ('event1', 1, '{str(uuid4())}', now(), 'some_distinct_id', '{properties}')
            ('event2', 1, '{str(uuid4())}', now(), 'some_distinct_id', '{properties}')
        """
    )


@pytest.mark.ee
class TestBackfillPersonsAndGroupsOnEvents(BaseTest, ClickhouseTestMixin):
    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def recreate_database(self):
        sync_execute(f"DROP DATABASE {settings.CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {settings.CLICKHOUSE_DATABASE}")
        create_clickhouse_tables()

    def test_person_backfill(self):
        self.recreate_database()

        create_test_events()

        person_id = uuid4()
        person_props = '{ "foo": "bar" }'
        sync_execute(
            f"""
            INSERT INTO person (id, team_id, properties)
            VALUES
                ('{str(person_id)}', 1, '{person_props}')
            """
        )

        sync_execute(
            f"""
            INSERT INTO person_distinct_id2 (person_id, distinct_id, team_id)
            VALUES
                ('{str(person_id)}', 'some_distinct_id', 1)
            """
        )

        events_before = sync_execute("select event, person_id, person_properties from events")
        self.assertEqual(
            events_before,
            [
                ("event1", UUID("00000000-0000-0000-0000-000000000000"), ""),
                ("event2", UUID("00000000-0000-0000-0000-000000000000"), ""),
            ],
        )

        run_backfill({"team_id": 1, "live_run": True})

        # even running the backfill synchronusly on tests seems to not be enough to ensure it's done yet
        sleep(10)

        events_after = sync_execute("select event, person_id, person_properties from events")
        self.assertEqual(
            events_after,
            [
                ("event1", person_id, '{ "foo": "bar" }'),
                ("event2", person_id, '{ "foo": "bar" }'),
            ],
        )

    def test_groups_backfill(self):
        self.recreate_database()

        create_test_events('{ "$group_0": "my_group" }')

        group_props = '{ "foo": "bar" }'
        sync_execute(
            f"""
            INSERT INTO groups (group_type_index, group_key, group_properties)
            VALUES
                (0, 'my_group', '{group_props}')
            """
        )

        events_before = sync_execute("select event, $group_0, group0_properties from events")
        self.assertEqual(events_before, [("event1", "my_group", ""), ("event2", "my_group", "")])

        run_backfill({"team_id": 1, "live_run": True})

        # even running the backfill synchronusly on tests seems to not be enough to ensure it's done yet
        sleep(10)

        events_after = sync_execute("select event, $group_0, group0_properties from events")
        self.assertEqual(
            events_after,
            [("event1", "my_group", group_props), ("event2", "my_group", group_props)],
        )

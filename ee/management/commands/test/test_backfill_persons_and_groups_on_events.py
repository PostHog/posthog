from uuid import UUID, uuid4

import pytest
from django.conf import settings

from ee.clickhouse.sql.events import EVENTS_DATA_TABLE
from ee.clickhouse.util import ClickhouseTestMixin
from ee.management.commands.backfill_persons_and_groups_on_events import run_backfill
from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.test.base import BaseTest


@pytest.mark.ee
class TestSyncReplicatedSchema(BaseTest, ClickhouseTestMixin):
    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def recreate_database(self, create_tables=True):
        sync_execute(f"DROP DATABASE {settings.CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {settings.CLICKHOUSE_DATABASE}")
        if create_tables:
            create_clickhouse_tables(0)

    def test_person_backfill(self):
        self.recreate_database(create_tables=True)

        sync_execute(
            f"""
            INSERT INTO {EVENTS_DATA_TABLE()} (event, team_id, uuid, timestamp, distinct_id)
            VALUES
                ('event1', 1, '{str(uuid4())}', now(), 'some_distinct_id')
                ('event2', 1, '{str(uuid4())}', now(), 'some_distinct_id')
            """
        )

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
            INSERT INTO person_distinct_id (person_id, distinct_id, team_id)
            VALUES
                ('{str(person_id)}', 'some_distinct_id', 1)
            """
        )

        events_before = sync_execute("select person_id, person_properties from events")
        self.assertEqual(
            events_before,
            [(UUID("00000000-0000-0000-0000-000000000000"), ""), (UUID("00000000-0000-0000-0000-000000000000"), "")],
        )

        run_backfill({"team_id": 1, "live_run": True})

        events_after = sync_execute("select person_id, person_properties from events")
        self.assertEqual(events_after, [(person_id, '{ "foo": "bar" }'), (person_id, '{ "foo": "bar" }')])

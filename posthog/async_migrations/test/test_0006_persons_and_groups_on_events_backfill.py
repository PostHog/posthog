import json
from typing import Dict, List

import pytest

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.client import query_with_columns, sync_execute
from posthog.models import Person
from posthog.models.event.util import create_event
from posthog.models.group.util import create_group
from posthog.models.person.util import create_person, create_person_distinct_id, delete_person
from posthog.models.utils import UUIDT
from posthog.test.base import ClickhouseTestMixin, run_clickhouse_statement_in_parallel

MIGRATION_NAME = "0006_persons_and_groups_on_events_backfill"

uuid1, uuid2, uuid3 = [UUIDT() for _ in range(3)]
# Clickhouse leaves behind blank/zero values for non-filled columns, these are checked against these constants
ZERO_UUID = UUIDT(uuid_str="00000000-0000-0000-0000-000000000000")
ZERO_DATE = "1970-01-01T00:00:00Z"


def run_migration():
    setup_async_migrations(ignore_posthog_version=True)
    return start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)


def query_events() -> List[Dict]:
    return query_with_columns(
        """
        SELECT
            distinct_id,
            person_id,
            person_properties,
            group0_properties,
            group1_properties,
            group2_properties,
            group3_properties,
            group4_properties,
            $group_0,
            $group_1,
            $group_2,
            $group_3,
            $group_4,
            formatDateTime(events.person_created_at, %(format)s) AS person_created_at,
            formatDateTime(events.group0_created_at, %(format)s) AS group0_created_at,
            formatDateTime(events.group1_created_at, %(format)s) AS group1_created_at,
            formatDateTime(events.group2_created_at, %(format)s) AS group2_created_at,
            formatDateTime(events.group3_created_at, %(format)s) AS group3_created_at,
            formatDateTime(events.group4_created_at, %(format)s) AS group4_created_at
        FROM events
        ORDER BY distinct_id
        """,
        {"format": "%Y-%m-%dT%H:%M:%SZ"},
    )


@pytest.mark.async_migrations
class Test0006PersonsAndGroupsOnEventsBackfill(AsyncMigrationBaseTest, ClickhouseTestMixin):
    def setUp(self):
        self.clear_tables()
        super().setUp()

    def tearDown(self):
        self.clear_tables()
        super().tearDown()

    def clear_tables(self):
        run_clickhouse_statement_in_parallel(
            [
                "TRUNCATE TABLE sharded_events",
                "DROP TABLE IF EXISTS tmp_person_0006",
                "DROP TABLE IF EXISTS tmp_person_distinct_id2_0006",
                "DROP TABLE IF EXISTS tmp_groups_0006",
                "DROP DICTIONARY IF EXISTS person_dict",
                "DROP DICTIONARY IF EXISTS person_distinct_id2_dict",
                "DROP DICTIONARY IF EXISTS groups_dict",
                "ALTER TABLE sharded_events MODIFY COLUMN person_properties VARCHAR CODEC(LZ4)",
            ]
        )

    def test_is_required(self):
        definition = get_async_migration_definition(MIGRATION_NAME)
        self.assertTrue(definition.is_required())

        run_migration()
        self.assertFalse(definition.is_required())

    def test_completes_successfully(self):
        self.assertTrue(run_migration())

    def test_data_copy_persons(self):
        create_event(
            event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview",
        )
        create_event(
            event_uuid=uuid2, team=self.team, distinct_id="2", event="$pageview",
        )
        create_event(
            event_uuid=uuid3, team=self.team, distinct_id="3", event="$pageview",
        )
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid1),
            properties={"personprop": 1},
            timestamp="2022-01-01T00:00:00Z",
        )
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid2),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_person_distinct_id(self.team.pk, "1", str(uuid1))
        create_person_distinct_id(self.team.pk, "2", str(uuid1))
        create_person_distinct_id(self.team.pk, "3", str(uuid2))

        self.assertTrue(run_migration())

        events = query_events()

        self.assertEqual(len(events), 3)
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "person_id": uuid1,
                "person_properties": json.dumps({"personprop": 1}),
                "person_created_at": "2022-01-01T00:00:00Z",
            },
            events[0],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2",
                "person_id": uuid1,
                "person_properties": json.dumps({"personprop": 1}),
                "person_created_at": "2022-01-01T00:00:00Z",
            },
            events[1],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "3",
                "person_id": uuid2,
                "person_properties": json.dumps({"personprop": 2}),
                "person_created_at": "2022-01-02T00:00:00Z",
            },
            events[2],
        )

    def test_duplicated_data_persons(self):
        create_event(
            event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview",
        )
        create_person_distinct_id(self.team.pk, "1", str(uuid1))
        create_person(
            team_id=self.team.pk,
            version=1,
            uuid=str(uuid1),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid1),
            properties={"personprop": 1},
            timestamp="2022-01-01T00:00:00Z",
        )

        self.assertTrue(run_migration())

        events = query_events()
        self.assertEqual(len(events), 1)
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "person_id": uuid1,
                "person_properties": json.dumps({"personprop": 2}),
                "person_created_at": "2022-01-02T00:00:00Z",
            },
            events[0],
        )

    def test_deleted_data_persons(self):
        create_event(
            event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview",
        )
        person = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        create_person_distinct_id(self.team.pk, "1", str(person.uuid))
        delete_person(person)

        self.assertTrue(run_migration())

        events = query_events()
        self.assertEqual(len(events), 1)
        self.assertDictContainsSubset(
            {"distinct_id": "1", "person_id": ZERO_UUID, "person_properties": "", "person_created_at": ZERO_DATE,},
            events[0],
        )

    def test_data_copy_groups(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
            timestamp="2022-01-01T00:00:00Z",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "IT"},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=2,
            group_key="77",
            properties={"index": 2},
            timestamp="2022-01-03T00:00:00Z",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=3,
            group_key="77",
            properties={"index": 3},
            timestamp="2022-01-04T00:00:00Z",
        )

        create_event(
            event_uuid=uuid1,
            team=self.team,
            distinct_id="1",
            event="$pageview",
            properties={"$group_0": "org:7", "$group_1": "77", "$group_2": "77", "$group_3": "77",},
        )

        self.assertTrue(run_migration())

        events = query_events()
        self.assertEqual(len(events), 1)
        self.assertDictContainsSubset(
            {
                "$group_0": "org:7",
                "group0_properties": json.dumps({"industry": "IT"}),
                "group0_created_at": "2022-01-02T00:00:00Z",
                "$group_1": "77",
                "group1_properties": "",
                "group1_created_at": ZERO_DATE,
                "$group_2": "77",
                "group2_properties": json.dumps({"index": 2}),
                "group2_created_at": "2022-01-03T00:00:00Z",
                "$group_3": "77",
                "group3_properties": json.dumps({"index": 3}),
                "group3_created_at": "2022-01-04T00:00:00Z",
                "$group_4": "",
                "group4_properties": "",
                "group4_created_at": ZERO_DATE,
            },
            events[0],
        )

    def test_no_extra_tables(self):
        initial_table_count = sync_execute("SELECT count() FROM system.tables")[0][0]
        initial_dictionary_count = sync_execute("SELECT count() FROM system.dictionaries")[0][0]

        run_migration()

        new_table_count = sync_execute("SELECT count() FROM system.tables")[0][0]
        new_dictionary_count = sync_execute("SELECT count() FROM system.dictionaries")[0][0]
        self.assertEqual(initial_table_count, new_table_count)
        self.assertEqual(initial_dictionary_count, new_dictionary_count)

    def test_rollback(self):
        pass

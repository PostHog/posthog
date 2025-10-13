import json
from uuid import uuid4

import pytest
from posthog.test.base import ClickhouseTestMixin, run_clickhouse_statement_in_parallel

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.clickhouse.client import query_with_columns, sync_execute
from posthog.models import Person
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus
from posthog.models.event.util import create_event
from posthog.models.group.util import create_group
from posthog.models.person.util import create_person, create_person_distinct_id, delete_person
from posthog.models.utils import UUIDT

pytestmark = pytest.mark.async_migrations

MIGRATION_NAME = "0007_persons_and_groups_on_events_backfill"

uuid1, uuid2, uuid3 = (UUIDT() for _ in range(3))
# Clickhouse leaves behind blank/zero values for non-filled columns, these are checked against these constants
ZERO_UUID = UUIDT(uuid_str="00000000-0000-0000-0000-000000000000")
ZERO_DATE = "1970-01-01T00:00:00Z"

MIGRATION_DEFINITION = get_async_migration_definition(MIGRATION_NAME)


def run_migration():
    setup_async_migrations(ignore_posthog_version=True)
    return start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)


def query_events() -> list[dict]:
    return query_with_columns(
        """
        SELECT
            distinct_id,
            person_id,
            person_properties,
            person_created_at,
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
        {"format": "%Y-%m-%dT%H:%i:%sZ"},
    )


class Test0007PersonsAndGroupsOnEventsBackfill(AsyncMigrationBaseTest, ClickhouseTestMixin):
    def setUp(self):
        MIGRATION_DEFINITION.parameters["TEAM_ID"] = (None, "", int)

        self.clear_tables()
        super().setUp()

    def tearDown(self):
        self.clear_tables()
        super().tearDown()

    def clear_tables(self):
        run_clickhouse_statement_in_parallel(
            [
                "TRUNCATE TABLE sharded_events",
                "TRUNCATE TABLE person",
                "TRUNCATE TABLE person_distinct_id",
                "DROP TABLE IF EXISTS tmp_person_0007",
                "DROP TABLE IF EXISTS tmp_person_distinct_id2_0007",
                "DROP TABLE IF EXISTS tmp_groups_0007",
                "DROP DICTIONARY IF EXISTS person_dict",
                "DROP DICTIONARY IF EXISTS person_distinct_id2_dict",
                "DROP DICTIONARY IF EXISTS groups_dict",
            ]
        )
        AsyncMigrationError.objects.all().delete()

    def test_is_required(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid1),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_person_distinct_id(self.team.pk, "1", str(uuid1))

        self.assertTrue(MIGRATION_DEFINITION.is_required())

        run_migration()
        self.assertFalse(MIGRATION_DEFINITION.is_required())

    def test_completes_successfully(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid1),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_person_distinct_id(self.team.pk, "1", str(uuid1))

        self.assertTrue(run_migration())

    def test_data_copy_persons(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_event(event_uuid=uuid2, team=self.team, distinct_id="2", event="$pageview")
        create_event(event_uuid=uuid3, team=self.team, distinct_id="3", event="$pageview")
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
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
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
        distinct_id = "not-reused-id"  # distinct ID re-use isn't supported after person deletion
        create_event(event_uuid=uuid1, team=self.team, distinct_id=distinct_id, event="$pageview")
        person = Person.objects.create(
            team_id=self.team.pk,
            distinct_ids=[distinct_id],
            properties={"$some_prop": "something", "$another_prop": "something"},
        )
        create_person_distinct_id(self.team.pk, distinct_id, str(person.uuid))
        delete_person(person)

        # the mutation will run as noted by person_properties becoming '{}' instead of ''
        # but the migration will be marked as false as it will fail the postcheck indicating some investigation is needed into the instance's data
        self.assertFalse(run_migration())

        events = query_events()
        self.assertEqual(len(events), 1)
        self.assertDictContainsSubset(
            {
                "distinct_id": distinct_id,
                "person_id": ZERO_UUID,
                "person_properties": "{}",
                "person_created_at": ZERO_DATE,
            },
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
            properties={
                "$group_0": "org:7",
                "$group_1": "77",
                "$group_2": "77",
                "$group_3": "77",
            },
        )

        # we need to also create person data so the backfill postcheck does not fail
        create_person_distinct_id(self.team.pk, "1", str(uuid1))
        create_person(
            team_id=self.team.pk,
            version=1,
            uuid=str(uuid1),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
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
                "group1_properties": "{}",
                "group1_created_at": ZERO_DATE,
                "$group_2": "77",
                "group2_properties": json.dumps({"index": 2}),
                "group2_created_at": "2022-01-03T00:00:00Z",
                "$group_3": "77",
                "group3_properties": json.dumps({"index": 3}),
                "group3_created_at": "2022-01-04T00:00:00Z",
                "$group_4": "",
                "group4_properties": "{}",
                "group4_created_at": ZERO_DATE,
            },
            events[0],
        )

    def test_no_extra_tables(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        initial_table_count = sync_execute("SELECT count() FROM system.tables")[0][0]
        initial_dictionary_count = sync_execute("SELECT count() FROM system.dictionaries")[0][0]

        run_migration()

        new_table_count = sync_execute("SELECT count() FROM system.tables")[0][0]
        new_dictionary_count = sync_execute("SELECT count() FROM system.dictionaries")[0][0]
        self.assertEqual(initial_table_count, new_table_count)
        self.assertEqual(initial_dictionary_count, new_dictionary_count)

    def test_rollback(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")

        old_fn = MIGRATION_DEFINITION.operations[-1].fn
        MIGRATION_DEFINITION.operations[-1].fn = lambda _: 0 / 0  # type: ignore

        migration_successful = run_migration()
        self.assertFalse(migration_successful)
        self.assertEqual(
            AsyncMigration.objects.get(name=MIGRATION_NAME).status,
            MigrationStatus.RolledBack,
        )

        MIGRATION_DEFINITION.operations[-1].fn = old_fn

    def test_timestamp_boundaries(self):
        _uuid1, _uuid2, _uuid3 = (UUIDT() for _ in range(3))
        create_event(
            event_uuid=_uuid1,
            team=self.team,
            distinct_id="1_outside_lower",
            event="$pageview",
            timestamp="2019-01-01T00:00:00Z",
        )
        create_event(
            event_uuid=_uuid2,
            team=self.team,
            distinct_id="2_outside_upper",
            event="$pageview",
            timestamp="2090-01-01T00:00:00Z",
        )
        create_event(
            event_uuid=_uuid3,
            team=self.team,
            distinct_id="3_in_range",
            event="$pageview",
            timestamp="2022-01-01T00:00:00Z",
        )

        create_person_distinct_id(self.team.pk, "1_outside_lower", str(_uuid1))
        create_person_distinct_id(self.team.pk, "2_outside_upper", str(_uuid2))
        create_person_distinct_id(self.team.pk, "3_in_range", str(_uuid3))

        create_person(
            team_id=self.team.pk,
            version=1,
            uuid=str(_uuid1),
            properties={"personprop": 1},
            timestamp="2022-01-01T00:00:00Z",
        )
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(_uuid2),
            properties={"personprop": 2},
            timestamp="2022-01-01T00:00:00Z",
        )
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(_uuid3),
            properties={"personprop": 3},
            timestamp="2022-01-01T00:00:00Z",
        )

        self.assertTrue(run_migration())

        events = query_events()
        self.assertEqual(len(events), 3)
        self.assertDictContainsSubset(
            {
                "distinct_id": "1_outside_lower",
                "person_id": ZERO_UUID,
                "person_properties": "",
                "person_created_at": ZERO_DATE,
            },
            events[0],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "2_outside_upper",
                "person_id": ZERO_UUID,
                "person_properties": "",
                "person_created_at": ZERO_DATE,
            },
            events[1],
        )
        self.assertDictContainsSubset(
            {
                "distinct_id": "3_in_range",
                "person_id": _uuid3,
                "person_properties": json.dumps({"personprop": 3}),
                "person_created_at": "2022-01-01T00:00:00Z",
            },
            events[2],
        )

    def test_team_id_filter_event_not_in_team(self):
        _uuid1 = UUIDT()
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_person_distinct_id(self.team.pk, "1", str(uuid1))

        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(_uuid1),
            properties={"personprop": 1},
            timestamp="2022-01-01T00:00:00Z",
        )

        MIGRATION_DEFINITION.parameters["TEAM_ID"] = (99999, "", int)

        self.assertTrue(run_migration())

        events = query_events()

        self.assertEqual(len(events), 1)
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "person_id": ZERO_UUID,
                "person_properties": "",
                "person_created_at": ZERO_DATE,
            },
            events[0],
        )

    def test_team_id_filter_event_in_team(self):
        _uuid1 = UUIDT()
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_person_distinct_id(self.team.pk, "1", str(_uuid1))

        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(_uuid1),
            properties={"personprop": 1},
            timestamp="2022-01-01T00:00:00Z",
        )

        MIGRATION_DEFINITION.parameters["TEAM_ID"] = (self.team.pk, "", int)

        self.assertTrue(run_migration())

        events = query_events()

        self.assertEqual(len(events), 1)
        self.assertDictContainsSubset(
            {
                "distinct_id": "1",
                "person_id": _uuid1,
                "person_properties": json.dumps({"personprop": 1}),
                "person_created_at": "2022-01-01T00:00:00Z",
            },
            events[0],
        )

    def test_postcheck_e2e(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid1),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_person_distinct_id(self.team.pk, "1", str(uuid1))

        self.assertTrue(run_migration())

    def test_check_person_data_success(self):
        create_event(event_uuid=uuid1, team=self.team, distinct_id="1", event="$pageview")
        create_person(
            team_id=self.team.pk,
            version=0,
            uuid=str(uuid1),
            properties={"personprop": 2},
            timestamp="2022-01-02T00:00:00Z",
        )
        create_person_distinct_id(self.team.pk, "1", str(uuid1))

        self.assertTrue(run_migration())

        MIGRATION_DEFINITION._check_person_data()  # type: ignore

    def test_check_person_data_failure(self):
        for i in range(100):
            _uuid = UUIDT()

            create_event(event_uuid=_uuid, team=self.team, distinct_id=str(i), event="$pageview")
            create_person(
                team_id=self.team.pk,
                version=0,
                uuid=str(_uuid),
                properties={"personprop": 2},
                timestamp="2022-01-02T00:00:00Z",
            )
            create_person_distinct_id(self.team.pk, str(i), str(_uuid))

        # missing person_id + backfill will not fix, since it has no associated person record
        create_event(
            event_uuid=UUIDT(),
            team=self.team,
            distinct_id="no_data_1",
            event="$pageview",
            person_id=ZERO_UUID,
            person_created_at="2022-01-02T00:00:00Z",
            person_properties={},
        )

        self.assertTrue(run_migration())

        # Test that we pass the postcheck when 1 out of 101 events is incomplete
        MIGRATION_DEFINITION._check_person_data()  # type: ignore

        # missing person_created_at
        create_event(
            event_uuid=UUIDT(),
            team=self.team,
            distinct_id="no_data_2",
            event="$pageview",
            person_id=uuid4(),
            person_properties={},
        )

        # missing person_id
        create_event(
            event_uuid=UUIDT(),
            team=self.team,
            distinct_id="no_data_3",
            event="$pageview",
            person_created_at="2022-01-02T00:00:00Z",
            person_properties={},
        )

        # Test that we fail the postcheck with the right message when 3 out of 101 events is incomplete (~2%)
        with self.assertRaisesRegex(
            Exception,
            "Backfill did not work succesfully. ~2% of events did not get the correct data for persons.",
        ):
            MIGRATION_DEFINITION._check_person_data()  # type: ignore

    def test_check_groups_data_success(self):
        # don't run the backfill so we can test the postcheck based only on the data we create
        old_fn = MIGRATION_DEFINITION.operations[-4].fn
        MIGRATION_DEFINITION.operations[-4].fn = lambda *args: None

        create_event(
            event_uuid=UUIDT(),
            team=self.team,
            distinct_id="1",
            event="$pageview",
            person_id=UUIDT(),
            person_created_at="2021-02-02T00:00:00Z",
            person_properties={},
            group0_properties={},
            group1_properties={},
            group2_properties={},
            group3_properties={},
            group4_properties={},
        )

        self.assertTrue(run_migration())

        MIGRATION_DEFINITION.operations[-4].fn = old_fn

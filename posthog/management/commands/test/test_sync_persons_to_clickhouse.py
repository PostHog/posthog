import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest import mock

from parameterized import parameterized
from psycopg.types.json import Jsonb

import posthog.management.commands.sync_persons_to_clickhouse
from posthog.clickhouse.client import sync_execute
from posthog.management.commands.sync_persons_to_clickhouse import (
    run,
    run_distinct_id_sync,
    run_group_sync,
    run_person_sync,
)
from posthog.models.group.sql import TRUNCATE_GROUPS_TABLE_SQL
from posthog.models.group.util import raw_create_group_ch
from posthog.models.person.sql import (
    PERSON_DISTINCT_ID2_TABLE,
    TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
    TRUNCATE_PERSON_TABLE_SQL,
)
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_group, insert_seed_person

pytestmark = pytest.mark.persons_db_direct


@pytest.mark.ee
class TestSyncPersonsToClickHouse(NonAtomicBaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        # NonAtomicBaseTest (TransactionTestCase) commits ORM fixtures so the command's raw
        # persons-DB read can see them, but it doesn't trigger the per-test ClickHouse reset the
        # atomic base provided — so clear the tables this command reconciles to isolate each test.
        sync_execute(TRUNCATE_PERSON_TABLE_SQL)
        sync_execute(TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL)
        sync_execute(TRUNCATE_GROUPS_TABLE_SQL)

    def test_persons_sync(self):
        person_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_person(
                conn,
                team_id=self.team.pk,
                properties={"a": 1234},
                is_identified=True,
                version=4,
                uuid=person_uuid,
            )

        run_person_sync(self.team.pk, live_run=True, deletes=False)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_persons, [(person_uuid, self.team.pk, '{"a": 1234}', True, 4, False)])

    def test_persons_sync_with_null_version(self):
        person_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_person(
                conn,
                team_id=self.team.pk,
                properties={"a": 1234},
                is_identified=True,
                version=None,
                uuid=person_uuid,
            )

        run_person_sync(self.team.pk, live_run=True, deletes=False)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_persons, [(person_uuid, self.team.pk, '{"a": 1234}', True, 0, False)])

    def test_persons_deleted(self):
        uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            version=5,
            properties={"abc": 123},
        )

        with fake_personhog_client() as personhog:
            # The only ClickHouse person is missing from Postgres, which is over the share limit.
            run_person_sync(self.team.pk, live_run=True, deletes=True, force=True)
            stored = personhog.stored_person(self.team.pk, uuid)

        # Postgres takes the tombstone first, so a later revival lands above the ClickHouse row.
        assert stored is not None and (stored.is_deleted, stored.version) == (True, 6)
        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person FINAL WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_persons, [(UUID(uuid), self.team.pk, "{}", False, 6, True)])

    def test_deletes_refuse_a_large_share_of_persons_missing_from_postgres(self):
        uuid = create_person(uuid=str(uuid4()), team_id=self.team.pk, version=5, properties={"abc": 123})

        with fake_personhog_client() as personhog, self.assertRaises(SystemExit):
            run_person_sync(self.team.pk, live_run=True, deletes=True)

        assert personhog.stored_person(self.team.pk, uuid) is None
        ch_persons = sync_execute(
            "SELECT version, is_deleted FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertEqual(ch_persons, [(5, False)])

    def test_a_person_live_on_the_postgres_primary_is_not_tombstoned(self):
        uuid = create_person(uuid=str(uuid4()), team_id=self.team.pk, version=5, properties={"abc": 123})

        # The sync's replica read misses the person; the primary, which the floor call reads, holds it live.
        with fake_personhog_client() as personhog:
            personhog.add_person(team_id=self.team.pk, person_id=1, uuid=uuid, version=5)
            run_person_sync(self.team.pk, live_run=True, deletes=True, force=True)

        ch_persons = sync_execute(
            "SELECT version, is_deleted FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        self.assertEqual(ch_persons, [(5, False)])

    @parameterized.expand(
        [
            # (name, ClickHouse live version, expected row after the sync)
            ("stored_version_wins", 5, ('{"abc": 123}', 9, True)),
            ("clickhouse_ahead_is_raised_above", 9, ('{"abc": 123}', 10, True)),
        ]
    )
    def test_persons_tombstoned_in_postgres_publish_the_stored_version(self, _name, ch_version, expected):
        person_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_person(conn, team_id=self.team.pk, properties={}, version=9, uuid=person_uuid)
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE posthog_person SET is_deleted = true WHERE team_id = %s AND uuid = %s",
                    [self.team.pk, person_uuid],
                )
        create_person(uuid=str(person_uuid), team_id=self.team.pk, version=ch_version, properties={"abc": 123})

        with fake_personhog_client():
            run_person_sync(self.team.pk, live_run=True, deletes=True)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, version, is_deleted FROM person FINAL WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        properties, version, is_deleted = expected
        # A tombstone at the stored version, never a +100 guess, so a later revival at version 10 wins.
        self.assertEqual(
            ch_persons, [(person_uuid, self.team.pk, "{}" if is_deleted else properties, version, is_deleted)]
        )

    def test_distinct_ids_sync(self):
        person_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            person_id = insert_seed_person(conn, team_id=self.team.pk, properties={}, version=0, uuid=person_uuid)
            insert_seed_distinct_id(conn, team_id=self.team.pk, person_id=person_id, distinct_id="test-id", version=4)

        run_distinct_id_sync(self.team.pk, live_run=True, deletes=False)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_person_distinct_ids, [(person_uuid, self.team.pk, "test-id", 4, False)])

    def test_distinct_ids_sync_with_null_version(self):
        person_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            person_id = insert_seed_person(conn, team_id=self.team.pk, properties={}, version=0, uuid=person_uuid)
            # version=None exercises the sync's NULL->0 coercion (the point of this test).
            insert_seed_distinct_id(
                conn, team_id=self.team.pk, person_id=person_id, distinct_id="test-id", version=None
            )

        run_distinct_id_sync(self.team.pk, live_run=True, deletes=False)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_person_distinct_ids, [(person_uuid, self.team.pk, "test-id", 0, False)])

    def test_distinct_ids_without_a_postgres_row_are_left_alone(self):
        uuid = uuid4()
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="test-id-7",
            person_id=str(uuid),
            is_deleted=False,
            version=7,
        )
        run_distinct_id_sync(self.team.pk, live_run=True, deletes=True)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        # A tombstone naming the all-zero person would be copied into events by the overrides squash.
        self.assertEqual(ch_person_distinct_ids, [(uuid, self.team.pk, "test-id-7", 7, False)])

    @parameterized.expand(
        [
            # (name, ClickHouse live version, expected version and is_deleted after the sync)
            ("stored_version_wins", 3, (7, True)),
            ("clickhouse_ahead_is_left_for_the_sweep", 7, (7, False)),
        ]
    )
    def test_distinct_ids_tombstoned_in_postgres_publish_the_stored_version(self, _name, ch_version, expected):
        person_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            person_id = insert_seed_person(conn, team_id=self.team.pk, properties={}, version=0, uuid=person_uuid)
            insert_seed_distinct_id(conn, team_id=self.team.pk, person_id=person_id, distinct_id="test-id", version=7)
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE posthog_persondistinctid SET is_deleted = true WHERE team_id = %s AND distinct_id = %s",
                    [self.team.pk, "test-id"],
                )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="test-id",
            person_id=str(person_uuid),
            is_deleted=False,
            version=ch_version,
        )

        run_distinct_id_sync(self.team.pk, live_run=True, deletes=True)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        version, is_deleted = expected
        self.assertEqual(ch_person_distinct_ids, [(person_uuid, self.team.pk, "test-id", version, is_deleted)])

    @mock.patch(
        f"{posthog.management.commands.sync_persons_to_clickhouse.__name__}.raw_create_group_ch",
        wraps=posthog.management.commands.sync_persons_to_clickhouse.raw_create_group_ch,
    )
    def test_group_sync(self, mocked_ch_call):
        ts = datetime.now(UTC)
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_type_index=2,
                group_key="group-key",
                group_properties={"a": 1234},
                created_at=ts,
                version=5,
            )

        run_group_sync(self.team.pk, live_run=True)
        mocked_ch_call.assert_called_once()

        ch_groups = sync_execute(
            """
            SELECT group_type_index, group_key, group_properties, created_at FROM groups WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(len(ch_groups), 1)
        ch_group = ch_groups[0]
        self.assertEqual(ch_group[0], 2)
        self.assertEqual(ch_group[1], "group-key")
        self.assertEqual(ch_group[2], '{"a": 1234}')
        self.assertEqual(ch_group[3].strftime("%Y-%m-%d %H:%M:%S"), ts.strftime("%Y-%m-%d %H:%M:%S"))

        # second time it's a no-op
        run_group_sync(self.team.pk, live_run=True)
        mocked_ch_call.assert_called_once()

    @mock.patch(
        f"{posthog.management.commands.sync_persons_to_clickhouse.__name__}.raw_create_group_ch",
        wraps=posthog.management.commands.sync_persons_to_clickhouse.raw_create_group_ch,
    )
    def test_group_sync_updates_group(self, mocked_ch_call):
        ts = datetime.now(UTC) - timedelta(hours=3)
        with persons_db_connection(writer=True, autocommit=True) as conn:
            group_id = insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_type_index=2,
                group_key="group-key",
                group_properties={"a": 5},
                created_at=ts,
                version=0,
            )
        # Seed with _timestamp=ts so the sync's re-insert is strictly newer: groups is
        # ReplacingMergeTree(ver=_timestamp) with second resolution, and a same-second tie
        # makes ORDER BY _timestamp DESC pick between the two rows arbitrarily
        raw_create_group_ch(self.team.pk, 2, "group-key", {"a": 5}, ts, timestamp=ts)
        with persons_db_connection(writer=True, autocommit=True) as conn, conn.cursor() as cursor:
            cursor.execute(
                "UPDATE posthog_group SET group_properties = %s WHERE id = %s",
                (Jsonb({"a": 5, "b": 3}), group_id),
            )

        ts_before = datetime.now(UTC)
        run_group_sync(self.team.pk, live_run=True)
        mocked_ch_call.assert_called_once()

        ch_groups = sync_execute(
            """
            SELECT group_type_index, group_key, group_properties, created_at, _timestamp FROM groups WHERE team_id = %(team_id)s ORDER BY _timestamp DESC LIMIT 1
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(len(ch_groups), 1)
        ch_group = ch_groups[0]
        self.assertEqual(ch_group[0], 2)
        self.assertEqual(ch_group[1], "group-key")
        self.assertEqual(ch_group[2], '{"a": 5, "b": 3}')
        self.assertEqual(
            ch_group[3].strftime("%Y-%m-%d %H:%M:%S"),
            ts.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.assertGreaterEqual(
            ch_group[4].strftime("%Y-%m-%d %H:%M:%S"),
            ts_before.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.assertLessEqual(
            ch_group[4].strftime("%Y-%m-%d %H:%M:%S"),
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        )

        # second time it's a no-op
        run_group_sync(self.team.pk, live_run=True)
        mocked_ch_call.assert_called_once()

    @mock.patch(
        f"{posthog.management.commands.sync_persons_to_clickhouse.__name__}.raw_create_group_ch",
        wraps=posthog.management.commands.sync_persons_to_clickhouse.raw_create_group_ch,
    )
    def test_group_sync_multiple_entries(self, mocked_ch_call):
        ts = datetime.now(UTC)
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_type_index=2,
                group_key="group-key",
                group_properties={"a": 1234},
                created_at=ts,
                version=5,
            )
            insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_type_index=2,
                group_key="group-key-2",
                group_properties={"a": 12345},
                created_at=ts,
                version=6,
            )
            insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_type_index=1,
                group_key="group-key",
                group_properties={"a": 123456},
                created_at=ts,
                version=7,
            )

        run_group_sync(self.team.pk, live_run=True)
        self.assertEqual(mocked_ch_call.call_count, 3)

        ch_groups = sync_execute(
            """
            SELECT group_type_index, group_key, group_properties FROM groups WHERE team_id = %(team_id)s ORDER BY group_type_index, group_key
            """,
            {"team_id": self.team.pk},
        )

        self.assertEqual(
            ch_groups,
            [
                (1, "group-key", '{"a": 123456}'),
                (2, "group-key", '{"a": 1234}'),
                (2, "group-key-2", '{"a": 12345}'),
            ],
        )

        # second time it's a no-op
        run_group_sync(self.team.pk, live_run=True)
        self.assertEqual(mocked_ch_call.call_count, 3)

    def test_live_run_everything(self):
        self.everything_test_run(True)

    def test_dry_run_everything(self):
        # verify we don't change anything
        self.everything_test_run(False)

    def everything_test_run(self, live_run):
        # 2 persons who shouldn't be changed
        person_not_changed_1_uuid = uuid4()
        person_not_changed_2_uuid = uuid4()
        person_should_be_created_1_uuid = uuid4()
        person_should_be_created_2_uuid = uuid4()
        person_should_update_1_uuid = uuid4()
        person_should_update_2_uuid = uuid4()
        with persons_db_connection(writer=True, autocommit=True) as conn:
            person_not_changed_1_id = insert_seed_person(
                conn, team_id=self.team.pk, properties={"abcdef": 1111}, version=0, uuid=person_not_changed_1_uuid
            )
            person_not_changed_2_id = insert_seed_person(
                conn, team_id=self.team.pk, properties={"abcdefg": 11112}, version=1, uuid=person_not_changed_2_uuid
            )

            # 2 persons who should be created
            insert_seed_person(
                conn,
                team_id=self.team.pk,
                properties={"abcde": 12553633},
                version=2,
                uuid=person_should_be_created_1_uuid,
            )
            insert_seed_person(
                conn,
                team_id=self.team.pk,
                properties={"abcdeit34": 12553633},
                version=3,
                uuid=person_should_be_created_2_uuid,
            )

            # 2 persons who have updates
            insert_seed_person(
                conn,
                team_id=self.team.pk,
                properties={"abcde": 12553},
                version=5,
                uuid=person_should_update_1_uuid,
            )
            insert_seed_person(
                conn, team_id=self.team.pk, properties={"abc": 125}, version=7, uuid=person_should_update_2_uuid
            )
        create_person(
            team_id=self.team.pk,
            properties={"abcdef": 1111},
            uuid=str(person_not_changed_1_uuid),
            version=0,
        )
        create_person(
            team_id=self.team.pk,
            properties={"abcdefg": 11112},
            uuid=str(person_not_changed_2_uuid),
            version=1,
        )
        create_person(
            uuid=str(person_should_update_1_uuid),
            team_id=self.team.pk,
            properties={"a": 13},
            version=4,
        )
        create_person(
            uuid=str(person_should_update_2_uuid),
            team_id=self.team.pk,
            properties={"a": 1},
            version=6,
        )

        # 2 persons need to be deleted
        deleted_person_1_uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            version=7,
            properties={"abcd": 123},
        )
        deleted_person_2_uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            version=8,
            properties={"abcef": 123},
        )

        # 2 distinct id no update
        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_distinct_id(
                conn,
                team_id=self.team.pk,
                person_id=person_not_changed_1_id,
                distinct_id="distinct_id",
                version=0,
            )
            insert_seed_distinct_id(
                conn,
                team_id=self.team.pk,
                person_id=person_not_changed_1_id,
                distinct_id="distinct_id-9",
                version=9,
            )

            # 2 distinct id to be created
            insert_seed_distinct_id(
                conn,
                team_id=self.team.pk,
                person_id=person_not_changed_1_id,
                distinct_id="distinct_id-10",
                version=10,
            )
            insert_seed_distinct_id(
                conn,
                team_id=self.team.pk,
                person_id=person_not_changed_1_id,
                distinct_id="distinct_id-11",
                version=11,
            )

            # 2 distinct id that need to update
            insert_seed_distinct_id(
                conn,
                team_id=self.team.pk,
                person_id=person_not_changed_2_id,
                distinct_id="distinct_id-12",
                version=13,
            )
            insert_seed_distinct_id(
                conn,
                team_id=self.team.pk,
                person_id=person_not_changed_2_id,
                distinct_id="distinct_id-14",
                version=15,
            )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id",
            person_id=str(person_not_changed_1_uuid),
            is_deleted=False,
            version=0,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-9",
            person_id=str(person_not_changed_1_uuid),
            is_deleted=False,
            version=9,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-12",
            person_id=str(person_not_changed_1_uuid),
            is_deleted=False,
            version=12,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-14",
            person_id=str(person_not_changed_1_uuid),
            is_deleted=False,
            version=14,
        )

        # 2 distinct ids need to be deleted
        deleted_distinct_id_1_uuid = uuid4()
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-17",
            person_id=str(deleted_distinct_id_1_uuid),
            is_deleted=False,
            version=17,
        )
        deleted_distinct_id_2_uuid = uuid4()
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-18",
            person_id=str(deleted_distinct_id_2_uuid),
            is_deleted=False,
            version=18,
        )

        with persons_db_connection(writer=True, autocommit=True) as conn:
            insert_seed_group(
                conn,
                team_id=self.team.pk,
                group_type_index=2,
                group_key="group-key",
                group_properties={"a": 1234},
                created_at=datetime.now(UTC) - timedelta(hours=3),
                version=5,
            )

        # Run the script for everything
        options = {
            "live_run": live_run,
            "team_id": self.team.pk,
            "person": True,
            "person_distinct_id": True,
            "person_override": True,
            "group": True,
            "deletes": True,
            # Two of its six ClickHouse persons are missing from Postgres, over the share limit.
            "force": True,
        }
        with fake_personhog_client():
            run(options)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person FINAL WHERE team_id = %(team_id)s ORDER BY version
            """,
            {"team_id": self.team.pk},
        )
        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s ORDER BY version
            """,
            {"team_id": self.team.pk},
        )
        ch_groups = sync_execute(
            """
            SELECT group_type_index, group_key, group_properties FROM groups WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )

        if not live_run:
            self.assertEqual(
                ch_persons,
                [
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        '{"abcdef": 1111}',
                        False,
                        0,
                        False,
                    ),
                    (
                        person_not_changed_2_uuid,
                        self.team.pk,
                        '{"abcdefg": 11112}',
                        False,
                        1,
                        False,
                    ),
                    (
                        person_should_update_1_uuid,
                        self.team.pk,
                        '{"a": 13}',
                        False,
                        4,
                        False,
                    ),
                    (
                        person_should_update_2_uuid,
                        self.team.pk,
                        '{"a": 1}',
                        False,
                        6,
                        False,
                    ),
                    (
                        UUID(deleted_person_1_uuid),
                        self.team.pk,
                        '{"abcd": 123}',
                        False,
                        7,
                        False,
                    ),
                    (
                        UUID(deleted_person_2_uuid),
                        self.team.pk,
                        '{"abcef": 123}',
                        False,
                        8,
                        False,
                    ),
                ],
            )
            self.assertEqual(
                ch_person_distinct_ids,
                [
                    (person_not_changed_1_uuid, self.team.pk, "distinct_id", 0, False),
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        "distinct_id-9",
                        9,
                        False,
                    ),
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        "distinct_id-12",
                        12,
                        False,
                    ),
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        "distinct_id-14",
                        14,
                        False,
                    ),
                    (
                        deleted_distinct_id_1_uuid,
                        self.team.pk,
                        "distinct_id-17",
                        17,
                        False,
                    ),
                    (
                        deleted_distinct_id_2_uuid,
                        self.team.pk,
                        "distinct_id-18",
                        18,
                        False,
                    ),
                ],
            )
            self.assertEqual(len(ch_groups), 0)
        else:
            self.assertEqual(
                ch_persons,
                [
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        '{"abcdef": 1111}',
                        False,
                        0,
                        False,
                    ),
                    (
                        person_not_changed_2_uuid,
                        self.team.pk,
                        '{"abcdefg": 11112}',
                        False,
                        1,
                        False,
                    ),
                    (
                        person_should_be_created_1_uuid,
                        self.team.pk,
                        '{"abcde": 12553633}',
                        False,
                        2,
                        False,
                    ),
                    (
                        person_should_be_created_2_uuid,
                        self.team.pk,
                        '{"abcdeit34": 12553633}',
                        False,
                        3,
                        False,
                    ),
                    (
                        person_should_update_1_uuid,
                        self.team.pk,
                        '{"abcde": 12553}',
                        False,
                        5,
                        False,
                    ),
                    (
                        person_should_update_2_uuid,
                        self.team.pk,
                        '{"abc": 125}',
                        False,
                        7,
                        False,
                    ),
                    (UUID(deleted_person_1_uuid), self.team.pk, "{}", False, 8, True),
                    (UUID(deleted_person_2_uuid), self.team.pk, "{}", False, 9, True),
                ],
            )
            self.assertEqual(
                ch_person_distinct_ids,
                [
                    (person_not_changed_1_uuid, self.team.pk, "distinct_id", 0, False),
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        "distinct_id-9",
                        9,
                        False,
                    ),
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        "distinct_id-10",
                        10,
                        False,
                    ),
                    (
                        person_not_changed_1_uuid,
                        self.team.pk,
                        "distinct_id-11",
                        11,
                        False,
                    ),
                    (
                        person_not_changed_2_uuid,
                        self.team.pk,
                        "distinct_id-12",
                        13,
                        False,
                    ),
                    (
                        person_not_changed_2_uuid,
                        self.team.pk,
                        "distinct_id-14",
                        15,
                        False,
                    ),
                    (deleted_distinct_id_1_uuid, self.team.pk, "distinct_id-17", 17, False),
                    (deleted_distinct_id_2_uuid, self.team.pk, "distinct_id-18", 18, False),
                ],
            )
            self.assertEqual(ch_groups, [(2, "group-key", '{"a": 1234}')])


@pytest.fixture(autouse=True)
def set_log_level(caplog):
    caplog.set_level(logging.INFO)

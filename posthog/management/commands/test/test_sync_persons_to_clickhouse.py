import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

import posthog.management.commands.sync_persons_to_clickhouse
from posthog.clickhouse.client import sync_execute
from posthog.management.commands.sync_persons_to_clickhouse import (
    run,
    run_distinct_id_sync,
    run_group_sync,
    run_person_sync,
)
from posthog.models.group.group import Group
from posthog.models.group.util import create_group
from posthog.models.person.person import Person, PersonDistinctId
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.signals import mute_selected_signals


@pytest.mark.ee
class TestSyncPersonsToClickHouse(BaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False

    def test_persons_sync(self):
        with mute_selected_signals():  # without creating/updating in clickhouse
            person = Person.objects.create(
                team_id=self.team.pk,
                properties={"a": 1234},
                is_identified=True,
                version=4,
                uuid=uuid4(),
            )

        run_person_sync(self.team.pk, live_run=True, deletes=False, sync=True)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_persons, [(person.uuid, self.team.pk, '{"a": 1234}', True, 4, False)])

    def test_persons_sync_with_null_version(self):
        with mute_selected_signals():  # without creating/updating in clickhouse
            person = Person.objects.create(
                team_id=self.team.pk,
                properties={"a": 1234},
                is_identified=True,
                version=None,
                uuid=uuid4(),
            )

        run_person_sync(self.team.pk, live_run=True, deletes=False, sync=True)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_persons, [(person.uuid, self.team.pk, '{"a": 1234}', True, 0, False)])

    def test_persons_deleted(self):
        uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            version=5,
            properties={"abc": 123},
            sync=True,
        )

        run_person_sync(self.team.pk, live_run=True, deletes=True, sync=True)

        ch_persons = sync_execute(
            """
            SELECT id, team_id, properties, is_identified, version, is_deleted FROM person FINAL WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_persons, [(UUID(uuid), self.team.pk, "{}", False, 105, True)])

    def test_distinct_ids_sync(self):
        with mute_selected_signals():  # without creating/updating in clickhouse
            person = Person.objects.create(team_id=self.team.pk, version=0, uuid=uuid4())
            PersonDistinctId.objects.create(team=self.team, person=person, distinct_id="test-id", version=4)

        run_distinct_id_sync(self.team.pk, live_run=True, deletes=False, sync=True)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_person_distinct_ids, [(person.uuid, self.team.pk, "test-id", 4, False)])

    def test_distinct_ids_sync_with_null_version(self):
        with mute_selected_signals():  # without creating/updating in clickhouse
            person = Person.objects.create(team_id=self.team.pk, version=0, uuid=uuid4())
            PersonDistinctId.objects.create(team=self.team, person=person, distinct_id="test-id", version=None)

        run_distinct_id_sync(self.team.pk, live_run=True, deletes=False, sync=True)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(ch_person_distinct_ids, [(person.uuid, self.team.pk, "test-id", 0, False)])

    def test_distinct_ids_deleted(self):
        uuid = uuid4()
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="test-id-7",
            person_id=str(uuid),
            is_deleted=False,
            version=7,
            sync=True,
        )
        run_distinct_id_sync(self.team.pk, live_run=True, deletes=True, sync=True)

        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(
            ch_person_distinct_ids,
            [(UUID(int=0), self.team.pk, "test-id-7", 107, True)],
        )

    @mock.patch(
        f"{posthog.management.commands.sync_persons_to_clickhouse.__name__}.raw_create_group_ch",
        wraps=posthog.management.commands.sync_persons_to_clickhouse.raw_create_group_ch,
    )
    def test_group_sync(self, mocked_ch_call):
        ts = datetime.now(UTC)
        Group.objects.create(
            team_id=self.team.pk,
            group_type_index=2,
            group_key="group-key",
            group_properties={"a": 1234},
            created_at=ts,
            version=5,
        )

        run_group_sync(self.team.pk, live_run=True, sync=True)
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
        run_group_sync(self.team.pk, live_run=True, sync=True)
        mocked_ch_call.assert_called_once()

    @mock.patch(
        f"{posthog.management.commands.sync_persons_to_clickhouse.__name__}.raw_create_group_ch",
        wraps=posthog.management.commands.sync_persons_to_clickhouse.raw_create_group_ch,
    )
    def test_group_sync_updates_group(self, mocked_ch_call):
        group = create_group(
            self.team.pk,
            2,
            "group-key",
            {"a": 5},
            timestamp=datetime.now(UTC) - timedelta(hours=3),
        )
        group.group_properties = {"a": 5, "b": 3}
        group.save()

        ts_before = datetime.now(UTC)
        run_group_sync(self.team.pk, live_run=True, sync=True)
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
            group.created_at.strftime("%Y-%m-%d %H:%M:%S"),
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
        run_group_sync(self.team.pk, live_run=True, sync=True)
        mocked_ch_call.assert_called_once()

    @mock.patch(
        f"{posthog.management.commands.sync_persons_to_clickhouse.__name__}.raw_create_group_ch",
        wraps=posthog.management.commands.sync_persons_to_clickhouse.raw_create_group_ch,
    )
    def test_group_sync_multiple_entries(self, mocked_ch_call):
        ts = datetime.now(UTC)
        Group.objects.create(
            team_id=self.team.pk,
            group_type_index=2,
            group_key="group-key",
            group_properties={"a": 1234},
            created_at=ts,
            version=5,
        )
        Group.objects.create(
            team_id=self.team.pk,
            group_type_index=2,
            group_key="group-key-2",
            group_properties={"a": 12345},
            created_at=ts,
            version=6,
        )
        Group.objects.create(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="group-key",
            group_properties={"a": 123456},
            created_at=ts,
            version=7,
        )

        run_group_sync(self.team.pk, live_run=True, sync=True)
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
        run_group_sync(self.team.pk, live_run=True, sync=True)
        self.assertEqual(mocked_ch_call.call_count, 3)

    def test_live_run_everything(self):
        self.everything_test_run(True)

    def test_dry_run_everything(self):
        # verify we don't change anything
        self.everything_test_run(False)

    def everything_test_run(self, live_run):
        # 2 persons who shouldn't be changed
        person_not_changed_1 = Person.objects.create(
            team_id=self.team.pk, properties={"abcdef": 1111}, version=0, uuid=uuid4()
        )
        person_not_changed_2 = Person.objects.create(
            team_id=self.team.pk, properties={"abcdefg": 11112}, version=1, uuid=uuid4()
        )

        # 2 persons who should be created
        with mute_selected_signals():  # without creating/updating in clickhouse
            person_should_be_created_1 = Person.objects.create(
                team_id=self.team.pk,
                properties={"abcde": 12553633},
                version=2,
                uuid=uuid4(),
            )
            person_should_be_created_2 = Person.objects.create(
                team_id=self.team.pk,
                properties={"abcdeit34": 12553633},
                version=3,
                uuid=uuid4(),
            )

            # 2 persons who have updates
            person_should_update_1 = Person.objects.create(
                team_id=self.team.pk,
                properties={"abcde": 12553},
                version=5,
                uuid=uuid4(),
            )
            person_should_update_2 = Person.objects.create(
                team_id=self.team.pk, properties={"abc": 125}, version=7, uuid=uuid4()
            )
        create_person(
            uuid=str(person_should_update_1.uuid),
            team_id=person_should_update_1.team.pk,
            properties={"a": 13},
            version=4,
            sync=True,
        )
        create_person(
            uuid=str(person_should_update_2.uuid),
            team_id=person_should_update_2.team.pk,
            properties={"a": 1},
            version=6,
            sync=True,
        )

        # 2 persons need to be deleted
        deleted_person_1_uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            version=7,
            properties={"abcd": 123},
            sync=True,
        )
        deleted_person_2_uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            version=8,
            properties={"abcef": 123},
            sync=True,
        )

        # 2 distinct id no update
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_not_changed_1,
            distinct_id="distinct_id",
            version=0,
        )
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_not_changed_1,
            distinct_id="distinct_id-9",
            version=9,
        )

        # # 2 distinct id to be created
        with mute_selected_signals():  # without creating/updating in clickhouse
            PersonDistinctId.objects.create(
                team=self.team,
                person=person_not_changed_1,
                distinct_id="distinct_id-10",
                version=10,
            )
            PersonDistinctId.objects.create(
                team=self.team,
                person=person_not_changed_1,
                distinct_id="distinct_id-11",
                version=11,
            )

            # 2 distinct id that need to update
            PersonDistinctId.objects.create(
                team=self.team,
                person=person_not_changed_2,
                distinct_id="distinct_id-12",
                version=13,
            )
            PersonDistinctId.objects.create(
                team=self.team,
                person=person_not_changed_2,
                distinct_id="distinct_id-14",
                version=15,
            )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-12",
            person_id=str(person_not_changed_1.uuid),
            is_deleted=False,
            version=12,
            sync=True,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-14",
            person_id=str(person_not_changed_1.uuid),
            is_deleted=False,
            version=14,
            sync=True,
        )

        # 2 distinct ids need to be deleted
        deleted_distinct_id_1_uuid = uuid4()
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-17",
            person_id=str(deleted_distinct_id_1_uuid),
            is_deleted=False,
            version=17,
            sync=True,
        )
        deleted_distinct_id_2_uuid = uuid4()
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-18",
            person_id=str(deleted_distinct_id_2_uuid),
            is_deleted=False,
            version=18,
            sync=True,
        )

        Group.objects.create(
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
        }
        run(options, sync=True)

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
                        person_not_changed_1.uuid,
                        self.team.pk,
                        '{"abcdef": 1111}',
                        False,
                        0,
                        False,
                    ),
                    (
                        person_not_changed_2.uuid,
                        self.team.pk,
                        '{"abcdefg": 11112}',
                        False,
                        1,
                        False,
                    ),
                    (
                        person_should_update_1.uuid,
                        self.team.pk,
                        '{"a": 13}',
                        False,
                        4,
                        False,
                    ),
                    (
                        person_should_update_2.uuid,
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
                    (person_not_changed_1.uuid, self.team.pk, "distinct_id", 0, False),
                    (
                        person_not_changed_1.uuid,
                        self.team.pk,
                        "distinct_id-9",
                        9,
                        False,
                    ),
                    (
                        person_not_changed_1.uuid,
                        self.team.pk,
                        "distinct_id-12",
                        12,
                        False,
                    ),
                    (
                        person_not_changed_1.uuid,
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
                        person_not_changed_1.uuid,
                        self.team.pk,
                        '{"abcdef": 1111}',
                        False,
                        0,
                        False,
                    ),
                    (
                        person_not_changed_2.uuid,
                        self.team.pk,
                        '{"abcdefg": 11112}',
                        False,
                        1,
                        False,
                    ),
                    (
                        person_should_be_created_1.uuid,
                        self.team.pk,
                        '{"abcde": 12553633}',
                        False,
                        2,
                        False,
                    ),
                    (
                        person_should_be_created_2.uuid,
                        self.team.pk,
                        '{"abcdeit34": 12553633}',
                        False,
                        3,
                        False,
                    ),
                    (
                        person_should_update_1.uuid,
                        self.team.pk,
                        '{"abcde": 12553}',
                        False,
                        5,
                        False,
                    ),
                    (
                        person_should_update_2.uuid,
                        self.team.pk,
                        '{"abc": 125}',
                        False,
                        7,
                        False,
                    ),
                    (UUID(deleted_person_1_uuid), self.team.pk, "{}", False, 107, True),
                    (UUID(deleted_person_2_uuid), self.team.pk, "{}", False, 108, True),
                ],
            )
            self.assertEqual(
                ch_person_distinct_ids,
                [
                    (person_not_changed_1.uuid, self.team.pk, "distinct_id", 0, False),
                    (
                        person_not_changed_1.uuid,
                        self.team.pk,
                        "distinct_id-9",
                        9,
                        False,
                    ),
                    (
                        person_not_changed_1.uuid,
                        self.team.pk,
                        "distinct_id-10",
                        10,
                        False,
                    ),
                    (
                        person_not_changed_1.uuid,
                        self.team.pk,
                        "distinct_id-11",
                        11,
                        False,
                    ),
                    (
                        person_not_changed_2.uuid,
                        self.team.pk,
                        "distinct_id-12",
                        13,
                        False,
                    ),
                    (
                        person_not_changed_2.uuid,
                        self.team.pk,
                        "distinct_id-14",
                        15,
                        False,
                    ),
                    (UUID(int=0), self.team.pk, "distinct_id-17", 117, True),
                    (UUID(int=0), self.team.pk, "distinct_id-18", 118, True),
                ],
            )
            self.assertEqual(ch_groups, [(2, "group-key", '{"a": 1234}')])


@pytest.fixture(autouse=True)
def set_log_level(caplog):
    caplog.set_level(logging.INFO)

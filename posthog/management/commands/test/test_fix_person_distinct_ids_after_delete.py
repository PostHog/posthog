import logging
from unittest import mock
from uuid import UUID, uuid4

import pytest

import posthog.management.commands.fix_person_distinct_ids_after_delete
from posthog.client import sync_execute
from posthog.management.commands.fix_person_distinct_ids_after_delete import run
from posthog.models.person.person import Person, PersonDistinctId
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.test.base import BaseTest, ClickhouseTestMixin


@pytest.mark.ee
class TestFixPersonDistinctIdsAfterDelete(BaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False

    @mock.patch(
        f"{posthog.management.commands.fix_person_distinct_ids_after_delete.__name__}.create_person_distinct_id",
        wraps=posthog.management.commands.fix_person_distinct_ids_after_delete.create_person_distinct_id,
    )
    def test_dry_run(self, mocked_ch_call):
        # clickhouse only deleted person and distinct id that should be updated
        ch_only_deleted_person_uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            is_deleted=True,
            version=5,
            sync=True,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id",
            person_id=ch_only_deleted_person_uuid,
            is_deleted=True,
            version=7,
            sync=True,
        )
        # reuse
        person_linked_to_after = Person.objects.create(
            team_id=self.team.pk, properties={"abcdefg": 11112}, version=1, uuid=uuid4()
        )
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_linked_to_after,
            distinct_id="distinct_id",
            version=0,
        )
        options = {"live_run": False, "team_id": self.team.pk, "new_version": 2500}
        run(options, True)

        # postgres didn't change
        pg_distinct_ids = PersonDistinctId.objects.all()
        self.assertEqual(len(pg_distinct_ids), 1)
        self.assertEqual(pg_distinct_ids[0].version, 0)
        self.assertEqual(pg_distinct_ids[0].distinct_id, "distinct_id")
        self.assertEqual(pg_distinct_ids[0].person.uuid, person_linked_to_after.uuid)

        # CH didn't change
        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s ORDER BY version
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(
            ch_person_distinct_ids,
            [
                (
                    UUID(ch_only_deleted_person_uuid),
                    self.team.pk,
                    "distinct_id",
                    7,
                    True,
                ),
            ],
        )
        mocked_ch_call.assert_not_called()

    @mock.patch(
        f"{posthog.management.commands.fix_person_distinct_ids_after_delete.__name__}.create_person_distinct_id",
        wraps=posthog.management.commands.fix_person_distinct_ids_after_delete.create_person_distinct_id,
    )
    def test_live_run(self, mocked_ch_call):
        # clickhouse only deleted person and distinct id that should be updated
        ch_only_deleted_person_uuid = create_person(
            uuid=str(uuid4()),
            team_id=self.team.pk,
            is_deleted=True,
            version=5,
            sync=True,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id",
            person_id=ch_only_deleted_person_uuid,
            is_deleted=True,
            version=7,
            sync=True,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id-2",
            person_id=ch_only_deleted_person_uuid,
            is_deleted=False,
            version=9,
            sync=True,
        )
        # reuse
        person_linked_to_after = Person.objects.create(
            team_id=self.team.pk, properties={"abcdefg": 11112}, version=1, uuid=uuid4()
        )
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_linked_to_after,
            distinct_id="distinct_id",
            version=0,
        )
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_linked_to_after,
            distinct_id="distinct_id-2",
            version=0,
        )
        options = {"live_run": True, "team_id": self.team.pk, "new_version": 2500}
        run(options, True)

        # postgres
        pg_distinct_ids = PersonDistinctId.objects.all()
        self.assertEqual(len(pg_distinct_ids), 2)
        self.assertEqual(pg_distinct_ids[0].version, 2500)
        self.assertEqual(pg_distinct_ids[1].version, 2500)
        self.assertEqual(
            {pg_distinct_ids[0].distinct_id, pg_distinct_ids[1].distinct_id},
            {"distinct_id", "distinct_id-2"},
        )
        self.assertEqual(pg_distinct_ids[0].person.uuid, person_linked_to_after.uuid)
        self.assertEqual(pg_distinct_ids[1].person.uuid, person_linked_to_after.uuid)

        # CH
        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s ORDER BY version, distinct_id
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(
            ch_person_distinct_ids,
            [
                (person_linked_to_after.uuid, self.team.pk, "distinct_id", 2500, False),
                (
                    person_linked_to_after.uuid,
                    self.team.pk,
                    "distinct_id-2",
                    2500,
                    False,
                ),
            ],
        )
        self.assertEqual(mocked_ch_call.call_count, 2)
        run(options, True)
        self.assertEqual(mocked_ch_call.call_count, 2)

    @mock.patch(
        f"{posthog.management.commands.fix_person_distinct_ids_after_delete.__name__}.create_person_distinct_id",
        wraps=posthog.management.commands.fix_person_distinct_ids_after_delete.create_person_distinct_id,
    )
    def test_no_op(self, mocked_ch_call):
        # person who shouldn't be changed
        person_not_changed_1 = Person.objects.create(
            team_id=self.team.pk, properties={"abcdef": 1111}, version=0, uuid=uuid4()
        )

        # distinct id no update
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_not_changed_1,
            distinct_id="distinct_id-1",
            version=0,
        )

        # deleted person not re-used
        person_deleted_1 = Person.objects.create(
            team_id=self.team.pk, properties={"abcdef": 1111}, version=0, uuid=uuid4()
        )
        PersonDistinctId.objects.create(
            team=self.team,
            person=person_deleted_1,
            distinct_id="distinct_id-del-1",
            version=16,
        )
        person_deleted_1.delete()

        options = {"live_run": True, "team_id": self.team.pk, "new_version": 2500}
        run(options, True)

        # postgres
        pg_distinct_ids = PersonDistinctId.objects.all()
        self.assertEqual(len(pg_distinct_ids), 1)
        self.assertEqual(pg_distinct_ids[0].version, 0)
        self.assertEqual(pg_distinct_ids[0].distinct_id, "distinct_id-1")
        self.assertEqual(pg_distinct_ids[0].person.uuid, person_not_changed_1.uuid)

        # clickhouse
        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s ORDER BY version
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(
            ch_person_distinct_ids,
            [
                (person_not_changed_1.uuid, self.team.pk, "distinct_id-1", 0, False),
                (person_deleted_1.uuid, self.team.pk, "distinct_id-del-1", 116, True),
            ],
        )
        mocked_ch_call.assert_not_called()


@pytest.fixture(autouse=True)
def set_log_level(caplog):
    caplog.set_level(logging.INFO)

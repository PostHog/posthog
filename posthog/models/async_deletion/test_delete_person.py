import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion.delete_person import DELETED_PERSON_IDS_DICTIONARY, remove_deleted_person_data
from posthog.models.person.util import create_person


def _visible_person_count(team_id: int) -> int:
    # SELECT excludes lightweight-deleted rows (_row_exists = 0). Scope to the test's team:
    # the ClickHouse person table is shared across the worker's tests and only truncated at
    # package teardown, so a whole-table count would see other tests' rows.
    return sync_execute("SELECT count() FROM person WHERE team_id = %(team_id)s", {"team_id": team_id})[0][0]


def _current_person_count(team_id: int) -> int:
    return sync_execute("SELECT count() FROM person FINAL WHERE team_id = %(team_id)s", {"team_id": team_id})[0][0]


def _dictionaries_exist() -> bool:
    # per-run dictionaries share a name prefix; none should remain after a run
    [[count]] = sync_execute(
        "SELECT count() FROM system.dictionaries WHERE database = %(db)s AND name LIKE %(prefix)s",
        {"db": settings.CLICKHOUSE_DATABASE, "prefix": f"{DELETED_PERSON_IDS_DICTIONARY}%"},
    )
    return count > 0


@pytest.mark.ee
class TestDeletePerson(BaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False

    def test_deletes_all_versions_of_soft_deleted_persons(self):
        # person A: a later version flips is_deleted -> every version of A must be removed,
        # which is why the delete keys on id rather than on is_deleted directly.
        uuid = create_person(team_id=self.team.pk, version=0, is_deleted=False)
        create_person(uuid=uuid, team_id=self.team.pk, version=1, is_deleted=True)
        # person B: single soft-deleted version
        create_person(team_id=self.team.pk, version=0, is_deleted=True)
        # person C: not deleted -> must remain
        create_person(team_id=self.team.pk, version=0)

        remove_deleted_person_data()

        # only person C remains visible (both versions of A + B are tombstoned)
        assert _visible_person_count(self.team.pk) == 1

    def test_preserves_persons_that_are_not_soft_deleted(self):
        create_person(team_id=self.team.pk, version=0)
        create_person(team_id=self.team.pk, version=0)

        remove_deleted_person_data()

        assert _visible_person_count(self.team.pk) == 2

    def test_preserves_revived_persons(self):
        # Soft-deleted at v0 then revived at v1 (newer version, not deleted): the person is
        # currently live, so the cleanup must preserve it.
        uuid = create_person(team_id=self.team.pk, version=0, is_deleted=True)
        create_person(uuid=uuid, team_id=self.team.pk, version=1, is_deleted=False)

        remove_deleted_person_data()

        assert _current_person_count(self.team.pk) == 1

    def test_no_op_when_nothing_is_soft_deleted(self):
        # Dictionary source query returns no rows -> dictHas is always false ->
        # nothing is deleted and the mutation must not error.
        create_person(team_id=self.team.pk, version=0)

        remove_deleted_person_data()

        assert _visible_person_count(self.team.pk) == 1

    def test_drops_the_dictionary_after_running(self):
        create_person(team_id=self.team.pk, version=0, is_deleted=True)

        remove_deleted_person_data()

        # the transient dictionary must not linger (it holds the id set in memory)
        assert not _dictionaries_exist()

    def test_is_idempotent(self):
        # After the first run the deleted rows are tombstoned (_row_exists = 0) and so
        # no longer appear in the dictionary source SELECT, so a second run is a no-op.
        create_person(team_id=self.team.pk, version=0, is_deleted=True)
        create_person(team_id=self.team.pk, version=0)

        remove_deleted_person_data()
        remove_deleted_person_data()

        assert _visible_person_count(self.team.pk) == 1

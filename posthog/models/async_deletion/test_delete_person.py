import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion.delete_person import remove_deleted_person_data
from posthog.models.person.util import create_person


@pytest.mark.ee
class TestDeletePerson(BaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False

    def test_delete_person(self):
        uuid = create_person(team_id=self.team.pk, version=0, is_deleted=False)
        create_person(uuid=uuid, team_id=self.team.pk, version=1, is_deleted=True)
        create_person(team_id=self.team.pk, version=0, is_deleted=True)
        create_person(team_id=self.team.pk, version=0)

        remove_deleted_person_data(mutations_sync=True)

        # Disable the trivial-count optimization: it sums each part's cached row count, and the
        # lightweight delete's per-part existing-rows count is recomputed asynchronously, so a
        # plain count() can still include the just-deleted rows. Forcing a real scan applies the
        # (already-synced) delete mask and makes the count deterministic.
        count = sync_execute("SELECT count() FROM person", settings={"optimize_trivial_count_query": 0})[0][0]

        assert count == 1

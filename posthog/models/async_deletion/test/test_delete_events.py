import pytest

from posthog.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person


@pytest.mark.ee
class TestDeleteEvetns(BaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False

    def test_delete_team(self):
        _create_event(
            distinct_id="whatever1",
            event="$event1",
            properties={"$lib": "$web"},
            team=self.team,
        )

        count = sync_execute("SELECT count() FROM events where team_id = %(team_id)s", {"team_id": self.team.pk})[0][0]
        assert count == 1
        AsyncDeletion.objects.create(deletion_type=0, team_id=self.team.pk, key=str(self.team.pk))

        from posthog.models.async_deletion.delete_events import AsyncEventDeletion

        runner = AsyncEventDeletion()

        runner.run()

        count = sync_execute("SELECT count() FROM events where team_id = %(team_id)s", {"team_id": self.team.pk})[0][0]
        assert count == 0

    def test_delete_person(self):
        person = _create_person(
            distinct_ids=["whatever1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            distinct_id="whatever1",
            event="$event1",
            properties={"$lib": "$web"},
            team=self.team,
        )

        # don't delete these ones
        _create_person(
            distinct_ids=["dontdelete"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            distinct_id="dontdelete",
            event="$event1",
            properties={"$lib": "$web"},
            team=self.team,
        )

        count = sync_execute("SELECT count() FROM events where team_id = %(team_id)s", {"team_id": self.team.pk})[0][0]
        assert count == 2
        AsyncDeletion.objects.create(deletion_type=1, team_id=self.team.pk, key=str(person.uuid))

        from posthog.models.async_deletion.delete_events import AsyncEventDeletion

        runner = AsyncEventDeletion()

        runner.run()

        count = sync_execute("SELECT count() FROM events where team_id = %(team_id)s", {"team_id": self.team.pk})[0][0]
        assert count == 1

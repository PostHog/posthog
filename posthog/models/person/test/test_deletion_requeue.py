from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.person.deletion_requeue import PendingDeletion, requeue_deletions
from posthog.test.persons import create_person

_DELAY = "posthog.tasks.delete_persons.delete_persons_async.delay"
_GAVE_UP_AT = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


class TestRequeueDeletions(BaseTest):
    def _deletion(self, team_id: int, uuids: list[str], gave_up_at: datetime | None = None) -> PendingDeletion:
        return PendingDeletion(
            team_id=team_id,
            person_uuids=uuids,
            delete_profile=True,
            delete_recordings=False,
            source="test",
            gave_up_at=gave_up_at,
        )

    @parameterized.expand(
        [
            ("dry_run", False, False, "would_queue", None),
            ("apply", True, False, "queued", (True, False)),
            ("recordings_only", True, True, "queued", (False, True)),
        ]
    )
    def test_queues_only_live_persons_with_the_requested_steps(self, _name, apply, recordings_only, outcome, flags):
        live = create_person(team=self.team, distinct_ids=["live-1"])
        gone = str(uuid4())

        with patch(_DELAY) as delay:
            results = requeue_deletions(
                [self._deletion(self.team.pk, [str(live.uuid), gone])], apply=apply, recordings_only=recordings_only
            )

        assert [(r.outcome, r.requested, r.live) for r in results] == [(outcome, 2, 1)]
        if flags is None:
            delay.assert_not_called()
        else:
            kwargs = delay.call_args.kwargs
            assert kwargs["person_uuids"] == [str(live.uuid)]
            assert (kwargs["delete_profile"], kwargs["delete_recordings"]) == flags

    @parameterized.expand(
        [
            ("deleted_after_the_give_up", timedelta(hours=1), True, "skipped_revived"),
            ("deleted_before_the_give_up", timedelta(hours=-1), True, "queued"),
            ("no_give_up_time", timedelta(hours=1), False, "queued"),
        ]
    )
    def test_leaves_alone_a_person_that_new_events_revived_after_the_give_up(
        self, _name: str, deleted_offset: timedelta, with_gave_up_at: bool, outcome: str
    ):
        person = create_person(team=self.team, distinct_ids=["returning"])
        ActivityLog.objects.create(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            scope="Person",
            activity="deleted",
            item_id=str(person.pk),
            created_at=_GAVE_UP_AT + deleted_offset,
        )

        with patch(_DELAY) as delay:
            results = requeue_deletions(
                [self._deletion(self.team.pk, [str(person.uuid)], _GAVE_UP_AT if with_gave_up_at else None)],
                apply=True,
            )

        assert [r.outcome for r in results] == [outcome]
        assert delay.called is (outcome == "queued")

    def test_skips_deletions_with_nothing_left_to_queue(self):
        with patch(_DELAY) as delay:
            results = requeue_deletions(
                [self._deletion(self.team.pk, [str(uuid4())]), self._deletion(999_999_999, [str(uuid4())])], apply=True
            )

        delay.assert_not_called()
        assert [r.outcome for r in results] == ["skipped_not_live", "skipped_team_gone"]

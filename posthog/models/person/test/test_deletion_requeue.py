import json
import base64
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

import fakeredis
from parameterized import parameterized

from posthog.models.person import deletion_requeue
from posthog.models.person.deletion_requeue import (
    UNACKED_HASH,
    UNACKED_INDEX,
    PendingDeletion,
    find_stuck_deletions,
    requeue_deletions,
)
from posthog.test.persons import create_person

_NOW = 1_800_000_000.0
_DELAY = "posthog.tasks.delete_persons.delete_persons_async.delay"


def _message(task: str, **kwargs) -> bytes:
    body = base64.b64encode(json.dumps([[], kwargs, {}]).encode()).decode()
    return json.dumps([{"body": body, "headers": {"task": task, "retries": 2}}, "", "celery"]).encode()


class TestFindStuckDeletions(SimpleTestCase):
    def test_lists_only_delete_tasks_in_the_age_window_across_pages_of_tied_scores(self):
        redis = fakeredis.FakeRedis()
        deletes: dict[str | bytes, float] = {f"tag-{i}": _NOW - 7200 for i in range(5)}
        for tag in deletes:
            redis.hset(
                UNACKED_HASH,
                tag,
                _message(
                    "posthog.tasks.delete_persons.delete_persons_async",
                    team_id=7,
                    person_uuids=[tag],
                    delete_profile=True,
                    delete_recordings=False,
                ),
            )
        redis.hset(
            UNACKED_HASH,
            "too-new",
            _message("posthog.tasks.delete_persons.delete_persons_async", team_id=7, person_uuids=["too-new"]),
        )
        redis.hset(UNACKED_HASH, "other-task", _message("posthog.tasks.other_task", team_id=7, person_uuids=["x"]))
        redis.zadd(UNACKED_INDEX, {**deletes, "too-new": _NOW - 60, "other-task": _NOW - 7200})

        with patch.object(deletion_requeue, "_HGET_BATCH", 2):
            found = list(
                find_stuck_deletions(redis, min_age_seconds=3600, max_age_seconds=86400, pause_seconds=0, now=_NOW)
            )

        assert sorted(d.person_uuids[0] for d in found) == sorted(str(tag) for tag in deletes)
        assert {(d.team_id, d.delete_profile, d.delete_recordings, d.retries) for d in found} == {(7, True, False, 2)}


class TestRequeueDeletions(BaseTest):
    def _deletion(self, team_id: int, uuids: list[str]) -> PendingDeletion:
        return PendingDeletion(
            team_id=team_id, person_uuids=uuids, delete_profile=True, delete_recordings=False, source="test"
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

    def test_skips_deletions_with_nothing_left_to_queue(self):
        with patch(_DELAY) as delay:
            results = requeue_deletions(
                [self._deletion(self.team.pk, [str(uuid4())]), self._deletion(999_999_999, [str(uuid4())])], apply=True
            )

        delay.assert_not_called()
        assert [r.outcome for r in results] == ["skipped_not_live", "skipped_team_gone"]

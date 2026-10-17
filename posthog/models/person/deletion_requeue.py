"""Find person deletions that never finished, and queue them again through the path the API uses."""

from __future__ import annotations

import json
import time
import base64
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from posthog.dataclasses import frozen
from posthog.models.person.util import get_persons_by_uuids
from posthog.models.team import Team
from posthog.tasks.delete_persons import queue_person_deletion

# Keys of kombu's Redis transport: the unacked hash holds each delivered message by delivery tag, and the
# sorted set scores each tag by its delivery time.
UNACKED_HASH = "unacked"
UNACKED_INDEX = "unacked_index"
_TASK_NAME = "delete_persons_async"
_HGET_BATCH = 500

RequeueOutcome = Literal["would_queue", "queued", "skipped_team_gone", "skipped_not_live"]


@frozen
class PendingDeletion:
    team_id: int
    person_uuids: list[str]
    delete_profile: bool
    delete_recordings: bool
    # Where the deletion was found; for a stuck broker message, when it was delivered and how often retried.
    source: str
    delivered_at: str | None = None
    retries: int | None = None


@frozen
class RequeueResult:
    team_id: int
    requested: int
    live: int
    outcome: RequeueOutcome
    delete_profile: bool
    delete_recordings: bool


def find_stuck_deletions(
    redis: Any,
    *,
    min_age_seconds: float,
    max_age_seconds: float,
    pause_seconds: float = 0.05,
    now: float | None = None,
) -> Iterator[PendingDeletion]:
    """Person deletion messages a worker took from the broker and never acknowledged, delivered between
    `max_age_seconds` and `min_age_seconds` ago. Reads only: it never changes the broker's keys."""
    now = time.time() if now is None else now
    for batch in _unacked_tags(redis, now - max_age_seconds, now - min_age_seconds):
        pipeline = redis.pipeline(transaction=False)
        for tag, _ in batch:
            pipeline.hget(UNACKED_HASH, tag)
        for (_, score), raw in zip(batch, pipeline.execute()):
            deletion = _parse_message(raw, score)
            if deletion is not None:
                yield deletion
        if pause_seconds:
            time.sleep(pause_seconds)


def _unacked_tags(redis: Any, low: float, high: float) -> Iterator[list[tuple[bytes, float]]]:
    """Pages of (tag, delivery time) in delivery order. Each page resumes at the last page's score and skips
    the tags it already returned at that score, so no single call reads the whole index."""
    score, seen_at_score = low, 0
    while True:
        page = redis.zrangebyscore(UNACKED_INDEX, score, high, start=seen_at_score, num=_HGET_BATCH, withscores=True)
        if not page:
            return
        yield page
        last = page[-1][1]
        at_last = sum(1 for _, s in page if s == last)
        seen_at_score = seen_at_score + at_last if last == score else at_last
        score = last


def _parse_message(raw: bytes | None, delivered_at: float) -> PendingDeletion | None:
    # Cheap filter first: the unacked hash holds every task type.
    if not raw or _TASK_NAME.encode() not in raw:
        return None
    message = json.loads(raw)[0]
    if not str(message.get("headers", {}).get("task", "")).endswith(_TASK_NAME):
        return None
    _, kwargs, _ = json.loads(base64.b64decode(message["body"]))
    return PendingDeletion(
        team_id=int(kwargs["team_id"]),
        person_uuids=list(kwargs.get("person_uuids") or []),
        delete_profile=bool(kwargs.get("delete_profile")),
        delete_recordings=bool(kwargs.get("delete_recordings")),
        source="broker_unacked",
        delivered_at=datetime.fromtimestamp(delivered_at, tz=UTC).isoformat(),
        retries=message["headers"].get("retries"),
    )


def requeue_deletions(
    deletions: Sequence[PendingDeletion],
    *,
    apply: bool,
    recordings_only: bool = False,
    on_result: Callable[[RequeueResult], None] = lambda _: None,
) -> list[RequeueResult]:
    """Queue each deletion's still-live persons again, with the same flags unless `recordings_only` is set.

    Only live persons are queued: a person whose profile is already deleted no longer resolves, so neither
    its profile nor its recordings can be found again.
    """
    results: list[RequeueResult] = []
    organizations = dict(
        Team.objects.filter(id__in={d.team_id for d in deletions}).values_list("id", "organization_id")
    )
    for deletion in deletions:
        delete_profile = False if recordings_only else deletion.delete_profile
        delete_recordings = True if recordings_only else deletion.delete_recordings
        organization_id = organizations.get(deletion.team_id)
        live = (
            get_persons_by_uuids(deletion.team_id, deletion.person_uuids, distinct_id_limit=0)
            if organization_id
            else []
        )
        if organization_id is None:
            outcome: RequeueOutcome = "skipped_team_gone"
        elif not live:
            outcome = "skipped_not_live"
        elif not apply:
            outcome = "would_queue"
        else:
            queue_person_deletion(
                deletion.team_id,
                live,
                delete_profile=delete_profile,
                delete_recordings=delete_recordings,
                actor=None,
                request=None,
                organization_id=organization_id,
            )
            outcome = "queued"
        result = RequeueResult(
            team_id=deletion.team_id,
            requested=len(deletion.person_uuids),
            live=len(live),
            outcome=outcome,
            delete_profile=delete_profile,
            delete_recordings=delete_recordings,
        )
        on_result(result)
        results.append(result)
    return results

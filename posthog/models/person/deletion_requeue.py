"""Queue person deletions that gave up again, through the path the API uses."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.person import Person
from posthog.models.person.util import get_persons_by_uuids
from posthog.models.team import Team
from posthog.tasks.delete_persons import queue_person_deletion

RequeueOutcome = Literal["would_queue", "queued", "skipped_team_gone", "skipped_not_live", "skipped_revived"]


@frozen
class PendingDeletion:
    team_id: int
    person_uuids: list[str]
    delete_profile: bool
    delete_recordings: bool
    source: str
    # When the deletion gave up. A person deleted after it and live again was revived by new events.
    gave_up_at: datetime | None = None


@frozen
class RequeueResult:
    team_id: int
    requested: int
    live: int
    revived: int
    outcome: RequeueOutcome
    delete_profile: bool
    delete_recordings: bool


def requeue_deletions(
    deletions: Sequence[PendingDeletion],
    *,
    apply: bool,
    recordings_only: bool = False,
    on_result: Callable[[RequeueResult], None] = lambda _: None,
) -> list[RequeueResult]:
    """Queue each deletion's still-live persons again, with the same flags unless `recordings_only` is set.

    Only live persons are queued: a person whose profile is already deleted no longer resolves. A live person
    that was deleted after `gave_up_at` came back through new events, so it is left alone rather than
    deleted along with the data recorded since.
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
        revived = _deleted_since(deletion.team_id, live, deletion.gave_up_at)
        pending = [p for p in live if str(p.pk) not in revived]
        if organization_id is None:
            outcome: RequeueOutcome = "skipped_team_gone"
        elif not live:
            outcome = "skipped_not_live"
        elif not pending:
            outcome = "skipped_revived"
        elif not apply:
            outcome = "would_queue"
        else:
            queue_person_deletion(
                deletion.team_id,
                pending,
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
            live=len(pending),
            revived=len(live) - len(pending),
            outcome=outcome,
            delete_profile=delete_profile,
            delete_recordings=delete_recordings,
        )
        on_result(result)
        results.append(result)
    return results


def _deleted_since(team_id: int, persons: list[Person], since: datetime | None) -> set[str]:
    """Primary keys of the persons with a deletion logged after `since`. The deletion path writes that entry
    only once a tombstone landed, and revival reuses the person's row, so the entry marks a revived person."""
    if since is None or not persons:
        return set()
    item_ids = ActivityLog.objects.filter(
        team_id=team_id,
        scope="Person",
        activity="deleted",
        item_id__in=[str(p.pk) for p in persons],
        created_at__gt=since,
    ).values_list("item_id", flat=True)
    return {item_id for item_id in item_ids if item_id is not None}

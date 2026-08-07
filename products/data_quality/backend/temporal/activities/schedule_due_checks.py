from datetime import UTC, datetime
from uuid import UUID

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from ...facade.enums import SubjectStatus
from ...logic.scheduling import advance_next_run_at, compute_shard_offset_seconds
from ...models import DataQualityCheck
from ..contracts import DueCheckGroup

LOGGER = get_logger(__name__)

# One scan should not be able to schedule the whole fleet; the next tick picks up the rest.
MAX_DUE_CHECKS_PER_SCAN = 2000


@activity.defn
async def retrieve_due_checks_activity() -> list[DueCheckGroup]:
    return await sync_to_async(_retrieve_due_checks)()


def _retrieve_due_checks() -> list[DueCheckGroup]:
    """Claim every check whose cadence has come round, grouped so one subject gets one suite run.

    ``next_run_at`` is advanced before the suites start, so a scan that overlaps the previous one
    cannot hand the same check to two suites.

    The trade-off is that claiming is not idempotent under retry: if an attempt commits the advance
    and then dies before Temporal records its result, the retry finds nothing due and those checks
    wait one cadence. Skipping a cycle is the deliberate choice over the alternative, which is
    double-running checks that execute warehouse queries. Making it exact needs a lease column and a
    two-phase claim; not worth the schema until someone sees a skipped cycle that mattered.
    """
    now = datetime.now(UTC)
    due = list(
        DataQualityCheck.objects.unscoped()
        .filter(
            enabled=True,
            deleted=False,
            next_run_at__lte=now,
            schedule_interval_minutes__gt=0,
        )
        .exclude(subject_status=SubjectStatus.ORPHANED)
        .order_by("next_run_at")[:MAX_DUE_CHECKS_PER_SCAN]
    )
    if not due:
        return []

    groups: dict[tuple[int, str, str], list[str]] = {}
    for check in due:
        # Non-null by the schedule_interval_minutes__gt=0 filter above; mypy can't see that.
        interval = check.schedule_interval_minutes or 0
        check.next_run_at = advance_next_run_at(
            interval,
            now,
            shard_offset_seconds=compute_shard_offset_seconds(UUID(str(check.id)), interval),
        )
        groups.setdefault((check.team_id, check.subject_type, str(check.subject_uuid)), []).append(str(check.id))

    DataQualityCheck.objects.unscoped().bulk_update(due, ["next_run_at"])
    LOGGER.info("Retrieved due checks", checks=len(due), groups=len(groups))

    return [
        DueCheckGroup(team_id=team_id, subject_type=subject_type, subject_uuid=subject_uuid, check_ids=check_ids)
        for (team_id, subject_type, subject_uuid), check_ids in groups.items()
    ]

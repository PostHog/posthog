"""The Celery task that copies one `posthog_integration` row to the credentials service.

The broker carries ids only. The task reads the row itself, so no secret passes through the queue,
and a late run sends the current row, not the one that was written.
"""

import datetime as dt

from django.conf import settings

import structlog
from celery import shared_task
from celery.utils.time import get_exponential_backoff_interval

from posthog.celery_queues import CeleryQueue
from posthog.integrations.backend.service_transport import IntegrationServiceUnavailable
from posthog.integrations.mirror.client import CONCURRENT_WRITE, MirrorClient, MirrorOrigin, MirrorOutcome, MirrorResult
from posthog.integrations.mirror.metrics import (
    FAILED,
    MIRROR_LAG,
    MIRROR_ROWS,
    MIRROR_TASK_GIVE_UPS,
    MIRROR_TASK_RETRIES,
)
from posthog.integrations.mirror.snapshot import MirrorDelete, MirrorRow, MirrorUpsert, read_snapshot
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)

MAX_RETRIES = 8
RETRY_BACKOFF_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 600

UNAVAILABLE = "unavailable"


def _send(client: MirrorClient, team_id: int, row: MirrorRow, origin: MirrorOrigin) -> MirrorResult:
    [result] = client.mirror(team_id, [row], origin=origin)
    MIRROR_ROWS.labels(kind=row.kind, outcome=result.outcome.value).inc()
    return result


def mirror_row(
    *,
    team_id: int,
    kind: str,
    legacy_id: int,
    team_gone: bool,
    origin: MirrorOrigin,
    client: MirrorClient | None = None,
) -> MirrorResult:
    """Mirrors the current state of one row. On a key conflict with another mirrored row, mirrors that row first."""
    client = client or MirrorClient()
    row: MirrorRow = (
        # The team's rows go with it, so no later upsert can come back for this id.
        MirrorDelete(legacy_id=legacy_id, kind=kind, tombstone=False)
        if team_gone
        else read_snapshot(team_id=team_id, kind=kind, legacy_id=legacy_id)
    )
    result = _send(client, team_id, row, origin)
    if (
        isinstance(row, MirrorUpsert)
        and result.outcome == MirrorOutcome.CONFLICT
        and not result.retryable
        and result.conflicting_legacy_id is not None
    ):
        # The stored copy of the key holder is out of date: it changed or lost the key in Django.
        holder = read_snapshot(team_id=team_id, kind=row.kind, legacy_id=result.conflicting_legacy_id)
        _send(client, team_id, holder, MirrorOrigin.REPAIR)
        result = _send(client, team_id, row, origin)
    return result


def _observe_lag(committed_at: str | None) -> None:
    if not committed_at:
        return
    try:
        committed = dt.datetime.fromisoformat(committed_at)
    except ValueError:
        return
    if committed.tzinfo is None:
        return
    MIRROR_LAG.observe(max(0.0, (dt.datetime.now(dt.UTC) - committed).total_seconds()))


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.INTEGRATIONS.value, max_retries=MAX_RETRIES)
@skip_team_scope_audit
def mirror_integration_row(
    self,
    team_id: int,
    kind: str,
    legacy_id: int,
    deleted: bool,
    team_gone: bool,
    committed_at: str | None = None,
) -> None:
    if not settings.CREDENTIALS_SERVICE_URL:
        return
    attempt = self.request.retries
    ids = {"team_id": team_id, "kind": kind, "legacy_id": legacy_id, "deleted": deleted, "attempt": attempt}
    try:
        result = mirror_row(
            team_id=team_id,
            kind=kind,
            legacy_id=legacy_id,
            team_gone=team_gone,
            origin=MirrorOrigin.RETRY if attempt else MirrorOrigin.WRITE,
        )
    except IntegrationServiceUnavailable as error:
        MIRROR_ROWS.labels(kind=kind, outcome=UNAVAILABLE).inc()
        reason, code = UNAVAILABLE, error.code
    except Exception as error:
        # The type and the service code only: a message could quote row content.
        MIRROR_ROWS.labels(kind=kind, outcome=FAILED).inc()
        logger.warning(
            "integration_mirror_failed",
            **ids,
            error_type=type(error).__name__,
            error_code=getattr(error, "code", None),
        )
        return
    else:
        _observe_lag(committed_at)
        if not result.retryable:
            if result.outcome in (MirrorOutcome.CONFLICT, MirrorOutcome.OWNER_MISMATCH, MirrorOutcome.REJECTED):
                logger.warning(
                    "integration_mirror_refused",
                    **ids,
                    outcome=result.outcome.value,
                    code=result.code,
                    conflicting_legacy_id=result.conflicting_legacy_id,
                )
            return
        reason, code = CONCURRENT_WRITE, result.code

    if attempt >= self.max_retries:
        MIRROR_TASK_GIVE_UPS.labels(reason=reason).inc()
        logger.warning("integration_mirror_gave_up", **ids, reason=reason, code=code)
        return
    MIRROR_TASK_RETRIES.labels(reason=reason).inc()
    delay = get_exponential_backoff_interval(
        factor=RETRY_BACKOFF_SECONDS, retries=attempt, maximum=MAX_RETRY_DELAY_SECONDS, full_jitter=True
    )
    raise self.retry(countdown=delay)

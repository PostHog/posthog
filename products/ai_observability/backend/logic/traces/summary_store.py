from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from django.core.cache import cache
from django.utils import timezone

from pydantic import Field, TypeAdapter, ValidationError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.property_access import restriction_fingerprint

from ...facade.contracts import TraceSummaryJob
from .summary import (
    FailedSummary,
    PendingSummary,
    SummaryEntry,
    SummaryKey,
    TraceSummaryNotFoundError,
    plan_request,
    require_ai_data_processing_approval,
    ttl_for,
)

_ENTRY = TypeAdapter[SummaryEntry](Annotated[SummaryEntry, Field(discriminator="status")])


def requester_fingerprint(team_id: int, user: User) -> str:
    return restriction_fingerprint(get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id))


def summary_key(team: Team, user: User, trace_id: str) -> SummaryKey:
    # Unlike the legacy summary key, an unrestricted user has a fingerprint too, so every key has one shape.
    return SummaryKey(team_id=team.pk, trace_id=trace_id, fingerprint=requester_fingerprint(team.pk, user))


def read_summary(key: SummaryKey) -> SummaryEntry | None:
    value = cache.get(key.cache_key)
    if not isinstance(value, str | bytes):
        return None
    try:
        return _ENTRY.validate_json(value)
    except ValidationError:
        return None


def _serialize(entry: SummaryEntry) -> str:
    return _ENTRY.dump_json(entry).decode()


def claim_summary(key: SummaryKey, entry: PendingSummary) -> bool:
    return cache.add(key.cache_key, _serialize(entry), timeout=ttl_for(entry).total_seconds())


def write_summary(key: SummaryKey, entry: SummaryEntry) -> None:
    cache.set(key.cache_key, _serialize(entry), timeout=ttl_for(entry).total_seconds())


def delete_summary(key: SummaryKey) -> None:
    cache.delete(key.cache_key)


def job_owns_entry(job: TraceSummaryJob) -> bool:
    """Whether the job's entry is still the pending one it was started for. A result already written, a newer
    request's entry, or an expired entry each mean the job has nothing left to do."""
    entry = read_summary(SummaryKey.for_job(job))
    return isinstance(entry, PendingSummary) and entry.requested_at == job.requested_at


def fail_abandoned_summary(job: TraceSummaryJob) -> None:
    """Mark the job's entry failed when the job ended without writing it, so it does not stay pending until it
    expires. An entry a later request replaced is left alone."""
    if job_owns_entry(job):
        write_summary(SummaryKey.for_job(job), FailedSummary(reason="error", failed_at=timezone.now()))


def viewer_summary(team: Team, user: User, trace_id: str) -> SummaryEntry:
    """The summary this viewer may see. Raises `TraceSummaryNotFoundError` when there is none."""
    require_ai_data_processing_approval(team.organization.is_ai_data_processing_approved)
    entry = read_summary(summary_key(team, user, trace_id))
    if entry is None:
        raise TraceSummaryNotFoundError(trace_id)
    return entry


@frozen
class _RequestEntry:
    entry: SummaryEntry
    written: bool


def _entry_for_request(key: SummaryKey, regenerate: bool) -> _RequestEntry:
    """The entry a request leaves behind: a ready summary to return, or the pending entry a job fills in."""
    existing = read_summary(key)
    plan = plan_request(existing, regenerate)
    if existing is not None and plan in ("return", "attach"):
        return _RequestEntry(entry=existing, written=False)
    pending = PendingSummary(requested_at=timezone.now())
    if plan == "claim":
        if claim_summary(key, pending):
            return _RequestEntry(entry=pending, written=True)
        # Another request claimed the key first, so its entry decides this one.
        winner = read_summary(key)
        if winner is not None and plan_request(winner, regenerate) in ("return", "attach"):
            return _RequestEntry(entry=winner, written=False)
    write_summary(key, pending)
    return _RequestEntry(entry=pending, written=True)


def request_summary(
    team: Team,
    user: User,
    trace_id: str,
    timestamp_hint: datetime | None,
    regenerate: bool,
    start: Callable[[TraceSummaryJob], None],
) -> SummaryEntry:
    """Return a ready summary, or make sure a job is writing one and return its pending entry.

    The entry is written before the job starts, so a fast job's result is never overwritten by `pending`."""
    require_ai_data_processing_approval(team.organization.is_ai_data_processing_approved)
    key = summary_key(team, user, trace_id)
    request_entry = _entry_for_request(key, regenerate)
    entry = request_entry.entry
    if not isinstance(entry, PendingSummary):
        return entry
    job = TraceSummaryJob(
        team_id=team.pk,
        trace_id=trace_id,
        timestamp_hint=timestamp_hint,
        fingerprint=key.fingerprint,
        requester_id=user.pk,
        requested_at=entry.requested_at,
    )
    try:
        start(job)
    except Exception as error:
        capture_exception(error, additional_properties={"team_id": team.pk})
        # The job of a reused entry may still run and write its result, so only an entry this request wrote fails.
        if not request_entry.written:
            return entry
        failed = FailedSummary(reason="error", failed_at=timezone.now())
        write_summary(key, failed)
        return failed
    return entry

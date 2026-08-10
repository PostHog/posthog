"""Reconstructs an organization's AI training opt-in history for the Django admin.

Everything here is derived from what was recorded: the organization's current field values and
the `ActivityLog` rows that changed `is_ai_training_opted_in`. The rules that decide the starting
value (region, license, HIPAA) are deliberately not reproduced here. A value with no recorded
change is reported as "no change recorded", and the raw flags are shown as-is for support to read.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization

AI_TRAINING_OPT_IN_FIELD = "is_ai_training_opted_in"

# Organizations log an ActivityLog row per changed field, so a busy org can accumulate a lot of
# rows. The admin page only needs enough to tell the story; anything beyond this is flagged.
MAX_ENTRIES_SHOWN = 50

RAW_STATUS_FIELDS = (
    "is_ai_training_opted_in",
    "is_ai_training_locked",
    "is_ai_training_cta_shown",
    "is_ai_data_processing_approved",
    "is_hipaa",
)


@dataclass(frozen=True)
class OptInChange:
    changed_at: datetime
    before: Optional[bool]
    after: Optional[bool]
    action: str
    actor: str
    origin: str
    was_impersonated: bool
    client: Optional[str]
    ip_address: Optional[str]
    activity_log_id: str
    raw_detail: Any

    @property
    def changed_at_display(self) -> str:
        return _timestamp(self.changed_at)

    @property
    def transition_display(self) -> str:
        return f"{_describe_value(self.before)} → {_describe_value(self.after)}"


@dataclass(frozen=True)
class OptInHistory:
    headline: str
    lines: list[str]
    changes: list[OptInChange]
    raw_status: list[tuple[str, Any]]
    truncated: bool = False
    error: Optional[str] = None


def _describe_value(value: Optional[bool]) -> str:
    if value is None:
        return "not set"
    return "opted in" if value else "opted out"


def _describe_actor(entry: ActivityLog) -> str:
    if entry.user is None:
        return "system"
    if entry.was_impersonated:
        return f"{entry.user.email} (session impersonated by PostHog staff)"
    return entry.user.email


def _describe_origin(entry: ActivityLog) -> str:
    if entry.user is not None:
        return "manual (staff impersonation)" if entry.was_impersonated else "manual"
    trigger = (entry.detail or {}).get("trigger") or {}
    job_type = trigger.get("job_type")
    return f"automatic ({job_type})" if job_type else "automatic"


def _opt_in_change_in(entry: ActivityLog) -> Optional[dict]:
    for change in (entry.detail or {}).get("changes") or []:
        if isinstance(change, dict) and change.get("field") == AI_TRAINING_OPT_IN_FIELD:
            return change
    return None


def _to_change(entry: ActivityLog, change: dict) -> OptInChange:
    return OptInChange(
        changed_at=entry.created_at,
        before=change.get("before"),
        after=change.get("after"),
        action=change.get("action") or "changed",
        actor=_describe_actor(entry),
        origin=_describe_origin(entry),
        was_impersonated=bool(entry.was_impersonated),
        client=entry.client,
        ip_address=entry.ip_address,
        activity_log_id=str(entry.id),
        raw_detail=entry.detail,
    )


def _fetch_changes(organization: Organization) -> tuple[list[OptInChange], bool]:
    # Newest-first so an organization over the cap keeps its most recent changes, which are the ones
    # support is asking about. Reversed below so the panel and the summary read oldest to newest.
    entries = list(
        ActivityLog.objects.filter(
            organization_id=organization.id,
            scope="Organization",
            item_id=str(organization.id),
            detail__changes__contains=[{"field": AI_TRAINING_OPT_IN_FIELD}],
        )
        .select_related("user")
        .order_by("-created_at")[: MAX_ENTRIES_SHOWN + 1]
    )

    truncated = len(entries) > MAX_ENTRIES_SHOWN
    changes = []
    for entry in reversed(entries[:MAX_ENTRIES_SHOWN]):
        change = _opt_in_change_in(entry)
        if change is not None:
            changes.append(_to_change(entry, change))
    return changes, truncated


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _build_summary(current: Optional[bool], changes: list[OptInChange], truncated: bool) -> tuple[str, list[str]]:
    ever_opted_in = current is True or any(c.after is True or c.before is True for c in changes)

    if current is True:
        headline = "Currently opted in"
    elif not ever_opted_in and not truncated:
        headline = "Never opted in"
    elif current is None:
        headline = "Currently not set"
    else:
        headline = "Currently opted out"

    if not changes:
        return headline, [
            f"Current value is {_describe_value(current)}.",
            "No change to this setting has ever been recorded, so it still holds the value the "
            "organization was given automatically.",
        ]

    lines = [f"Current value is {_describe_value(current)}."]

    if truncated:
        lines.append(
            f"More than {MAX_ENTRIES_SHOWN} changes recorded. Only the most recent {len(changes)} are "
            "summarized here, so anything before them is missing from this panel."
        )
    else:
        lines.append(f"{len(changes)} recorded change(s).")
        lines.append(
            f"Before the first recorded change it was {_describe_value(changes[0].before)}, with no "
            "earlier change recorded, so that value was set automatically."
        )

    first_opt_in = next((c for c in changes if c.after is True), None)
    if first_opt_in is None:
        if changes[0].before is not True:
            lines.append("None of these changes switched it on.")
    else:
        lines.append(
            f"{'Earliest shown opt-in' if truncated else 'First opted in'} on "
            f"{_timestamp(first_opt_in.changed_at)} by {first_opt_in.actor} ({first_opt_in.origin})."
        )

    last = changes[-1]
    lines.append(
        f"Last changed on {_timestamp(last.changed_at)} by {last.actor} ({last.origin}): {last.transition_display}."
    )

    return headline, lines


def get_ai_training_opt_in_history(organization: Organization) -> OptInHistory:
    raw_status: list[tuple[str, Any]] = [(name, getattr(organization, name, None)) for name in RAW_STATUS_FIELDS]
    raw_status.append(("created_at", organization.created_at))

    try:
        changes, truncated = _fetch_changes(organization)
    except Exception as e:
        return OptInHistory(
            headline="Could not load history",
            lines=[],
            changes=[],
            raw_status=raw_status,
            error=str(e),
        )

    headline, lines = _build_summary(organization.is_ai_training_opted_in, changes, truncated)
    return OptInHistory(
        headline=headline,
        lines=lines,
        changes=changes,
        raw_status=raw_status,
        truncated=truncated,
    )

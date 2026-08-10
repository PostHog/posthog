"""Reconstructs an organization's AI training opt-in history for the Django admin.

Everything here is derived from what was recorded: the organization's current value and the
`ActivityLog` rows that changed `is_ai_training_opted_in`. The rules that decide the starting
value (region, license, HIPAA) are deliberately not reproduced here.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from django.db import transaction

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization

# Matches `detail.changes[].field`, which carries the *display* name from `field_name_overrides`.
# It equals the model field name only because Organization has no override for this field; adding
# one would silently empty this panel, which `test_manual_opt_in_then_opt_out...` would catch.
AI_TRAINING_OPT_IN_FIELD = "is_ai_training_opted_in"

# One ActivityLog row per organization save, carrying every field changed in that save, so a row
# holds at most one opt-in change. 50 rows means 50 actual toggles; beyond that the panel says so.
MAX_ENTRIES_SHOWN = 50


@dataclass(frozen=True)
class OptInChange:
    changed_at: datetime
    before: Optional[bool]
    after: Optional[bool]
    actor: str
    origin: str
    client: Optional[str]
    ip_address: Optional[str]

    @property
    def changed_at_display(self) -> str:
        return _timestamp(self.changed_at)

    @property
    def transition_display(self) -> str:
        return f"{_describe_value(self.before)} → {_describe_value(self.after)}"


@dataclass(frozen=True)
class OptInHistory:
    headline: str
    changes: list[OptInChange]
    truncated: bool = False
    error: Optional[str] = None


def _describe_value(value: Optional[bool]) -> str:
    if value is None:
        return "not set"
    return "opted in" if value else "opted out"


def _was_system(entry: ActivityLog) -> bool:
    # is_system is written as `user is None` and then frozen, while user is SET_NULL on delete. So a
    # null user alone does not mean automation: it also describes a change by a since-deleted person.
    if entry.is_system is None:
        return entry.user_id is None
    return entry.is_system


def _describe_actor(entry: ActivityLog) -> str:
    if entry.user is not None:
        if entry.was_impersonated:
            return f"{entry.user.email} (acting-as, PostHog staff member not recorded)"
        return entry.user.email
    return "system" if _was_system(entry) else "user since deleted"


def _describe_origin(entry: ActivityLog) -> str:
    if _was_system(entry):
        return "automatic"
    return "manual (staff impersonation)" if entry.was_impersonated else "manual"


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
        actor=_describe_actor(entry),
        origin=_describe_origin(entry),
        client=entry.client,
        ip_address=entry.ip_address,
    )


def _fetch_changes(organization: Organization) -> tuple[list[OptInChange], bool]:
    # Newest-first so an organization over the cap keeps its most recent changes, which are the ones
    # support is asking about. Reversed below so the panel reads oldest to newest.
    entries = list(
        ActivityLog.objects.filter(
            organization_id=organization.id,
            scope="Organization",
            item_id=str(organization.id),
            # Whole-column containment, not `detail__changes__contains`: jsonb containment is
            # recursive so this matches the same rows, but only this form can use the GIN index on
            # detail. Filtering on `detail -> 'changes'` scans the org's whole activity history.
            detail__contains={"changes": [{"field": AI_TRAINING_OPT_IN_FIELD}]},
        )
        .select_related("user")
        .order_by("-created_at", "-id")[: MAX_ENTRIES_SHOWN + 1]
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


def _build_headline(current: Optional[bool], changes: list[OptInChange]) -> str:
    if current is True:
        return "Currently opted in"

    was_opted_in = any(c.after is True or c.before is True for c in changes)
    headline = "Currently opted out, was opted in previously" if was_opted_in else "Never opted in"
    # The column is nullable, and null reads as opted out everywhere else. Say so rather than let
    # support assume someone set it to false.
    return f"{headline} (value is null)" if current is None else headline


def get_ai_training_opt_in_history(organization: Organization) -> OptInHistory:
    try:
        # Savepoint so a failed query rolls back cleanly: the admin wraps change-form POSTs in a
        # transaction, and swallowing the error without this leaves it aborted, turning a form
        # validation error into an opaque 500 from the next unrelated query.
        with transaction.atomic():
            changes, truncated = _fetch_changes(organization)
    except Exception as e:
        capture_exception(e)
        return OptInHistory(headline="Could not load opt-in history", changes=[], error=str(e))

    return OptInHistory(
        headline=_build_headline(organization.is_ai_training_opted_in, changes),
        changes=changes,
        truncated=truncated,
    )

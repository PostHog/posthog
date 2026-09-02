"""Reconstructs an organization's AI training opt-in history for the Django admin.

This module reads two sources: the organization's current value, and the `ActivityLog` rows that
changed `is_ai_training_opted_in`. It reports only what those sources recorded. It does not repeat
the rules that set the starting value. Those rules cover region, license, and HIPAA.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from django.db import transaction
from django.db.models import Q

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization

# This value matches `detail.changes[].field`. That key holds the display name from
# `field_name_overrides`. It equals the model field name because Organization sets no override for
# this field. An override would empty this panel. `test_manual_opt_in_then_opt_out...` catches that.
AI_TRAINING_OPT_IN_FIELD = "is_ai_training_opted_in"

# Each organization save writes one ActivityLog row. That row holds every field the save changed, so
# it holds at most one opt-in change. 50 rows mean 50 toggles. The panel reports any row above 50.
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
    warning: Optional[str] = None
    truncated: bool = False
    error: Optional[str] = None


def _describe_value(value: Optional[bool]) -> str:
    if value is None:
        return "not set"
    return "opted in" if value else "opted out"


def _was_system(entry: ActivityLog) -> bool:
    # log_activity sets is_system from `user is None` and never updates it. Deleting a user sets the
    # user column to null. A null user therefore means automation or a deleted person.
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
    # This return is defensive. _opt_in_activity only admits rows that hold an opt-in change, so this line does not run.
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


def _opt_in_activity(organization: Organization):
    return ActivityLog.objects.filter(
        organization_id=organization.id,
        scope="Organization",
        item_id=str(organization.id),
        # This filter uses whole-column containment, not `detail__changes__contains`. Both match the
        # same rows, because jsonb containment is recursive. Only this form uses the GIN index on
        # detail. A filter on `detail -> 'changes'` scans the organization's whole activity history.
        detail__contains={"changes": [{"field": AI_TRAINING_OPT_IN_FIELD}]},
    )


def _was_opted_in(organization: Organization, changes: list[OptInChange], truncated: bool) -> bool:
    if any(c.after is True or c.before is True for c in changes):
        return True
    # A window that holds every row is the whole history, so the scan above already answered this.
    # Only a truncated window can hide an older opt-in, so only it needs the uncapped query.
    return truncated and _has_recorded_opt_in(organization)


def _has_recorded_opt_in(organization: Organization) -> bool:
    return (
        _opt_in_activity(organization)
        .filter(
            Q(detail__contains={"changes": [{"field": AI_TRAINING_OPT_IN_FIELD, "after": True}]})
            | Q(detail__contains={"changes": [{"field": AI_TRAINING_OPT_IN_FIELD, "before": True}]})
        )
        .exists()
    )


def _fetch_changes(organization: Organization) -> tuple[list[OptInChange], bool]:
    # This query sorts newest first, so an organization above the cap keeps its most recent changes.
    # Support asks about those. The loop below reverses them, so the panel reads oldest to newest.
    entries = list(
        _opt_in_activity(organization).select_related("user").order_by("-created_at", "-id")[: MAX_ENTRIES_SHOWN + 1]
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


def _build_headline(current: Optional[bool], was_opted_in: bool) -> str:
    if current is True:
        return "Currently opted in"

    # This says "No recorded opt-in", not "Never opted in". Two paths leave no row to find: an
    # opt-out written outside the ORM, and an activity-log write that failed.
    headline = "Currently opted out, was opted in previously" if was_opted_in else "No recorded opt-in"
    # The column accepts null, and every other surface reads null as opted out. Name the null value
    # here, so support does not assume that a person set the column to false.
    return f"{headline} (value is null)" if current is None else headline


def _hipaa_conflict_warning(organization: Organization) -> Optional[str]:
    # The replay ML mirror reads is_ai_training_opted_in alone. That gate is in
    # nodejs/src/ingestion/pipelines/sessionreplay/ai-training-optin-filter-step.ts. No code in that
    # pipeline reads is_hipaa. Change this warning if that gate starts to read is_hipaa.
    if not organization.is_hipaa or organization.is_ai_training_opted_in is not True:
        return None
    return (
        "HIPAA is set, but the AI training opt-in is on. The training pipeline reads the opt-in and "
        "does not check HIPAA, so this organization's session recordings are eligible for training. "
        "Their settings page shows them as opted out, and the API blocks them from changing it "
        "themselves. Turn the opt-in off here if that is wrong."
    )


def get_ai_training_opt_in_history(organization: Organization) -> OptInHistory:
    try:
        # This savepoint rolls a failed query back cleanly. The admin runs each change-form POST in
        # a transaction. Without the savepoint, a caught error leaves that transaction aborted, and
        # the next query turns a form validation error into a 500.
        with transaction.atomic():
            changes, truncated = _fetch_changes(organization)
            was_opted_in = _was_opted_in(organization, changes, truncated)
    except Exception as e:
        capture_exception(e)
        return OptInHistory(headline="Could not load opt-in history", changes=[], error=str(e))

    return OptInHistory(
        headline=_build_headline(organization.is_ai_training_opted_in, was_opted_in),
        changes=changes,
        warning=_hipaa_conflict_warning(organization),
        truncated=truncated,
    )

"""Shared helpers for resource-level `/revert/` endpoints backed by the activity log.

Any resource that already records changes through `log_activity()` (whether via the
`ModelActivityMixin` signal or imperative calls) can opt in to a revert endpoint by
wiring three pieces into its viewset:

1. A scoped `revert` action that calls `get_object()` (to enforce the resource's
   existing edit permissions) and uses `RevertActivityLogRequestSerializer` for
   the request body.
2. A call to `lookup_revertable_activity_log_entry()` with the resource's scope
   and the `item_id` form the resource's `log_activity()` calls write (some
   resources use the integer pk, others use a short_id — match what's stored).
3. A call to `apply_revert_to_instance()` with a *whitelist* of safe scalar /
   JSON fields. Exclude foreign keys (their serialized JSON form does not round
   trip), m2m relations, derived fields, soft-delete flags, and any field that
   carries its own write semantics (e.g. optimistic-concurrency counters).

For resources that use `ModelActivityMixin`, `instance.save()` after the revert
will record a fresh activity log entry automatically. For resources that log
activity imperatively (Insight, Notebook, etc.), the action must also call the
resource's existing activity logger after save so the revert is itself recorded.

`DashboardsViewSet.revert` and `InsightViewSet.revert` are the reference call
sites. The matching MCP tools live under each product's `mcp/tools.yaml`.
"""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import Model

import posthoganalytics
from rest_framework import exceptions, serializers

from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    ActivityScope,
    apply_activity_visibility_restrictions,
    apply_organization_scoped_filter,
)
from posthog.models.user import User

if TYPE_CHECKING:
    from posthog.models.team.team import Team


# Server-side PostHog feature flag that gates every `/revert/` endpoint built on
# these helpers. Off by default so the feature can be smoke-tested on internal
# teams in production before opening up to all customers. Enable the flag in the
# PostHog UI / API for the orgs you want to give access to.
ACTIVITY_LOG_REVERT_FLAG = "activity-log-revert"


def is_activity_log_revert_enabled(user: "User", team: "Team") -> bool:
    distinct_id = user.distinct_id or str(user.uuid)
    organization_id = str(team.organization_id)
    project_id = str(team.id)
    return bool(
        posthoganalytics.feature_enabled(
            ACTIVITY_LOG_REVERT_FLAG,
            distinct_id,
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


class RevertActivityLogRequestSerializer(serializers.Serializer):
    """Shared request body for resource-level `/revert/` endpoints."""

    activity_log_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional UUID of the ActivityLog entry to revert. If omitted, the endpoint "
            "picks the most recent revertable entry for this resource — the natural "
            "meaning of 'undo my last change'. The chosen entry's id is returned in "
            "`activity_log_id` so callers can confirm what was reverted. Use "
            "activity-log-list or advanced-activity-logs-list to inspect candidates "
            "when a specific past state needs to be restored."
        ),
    )


# Number of recent activity log entries to scan when falling back to the most recent
# revertable entry. Bounded so a long-lived resource with thousands of edits doesn't
# slow the request down. If none of the last `FALLBACK_LOOKBACK_LIMIT` entries are
# revertable, the endpoint returns 404 and the caller must supply an explicit id.
FALLBACK_LOOKBACK_LIMIT = 50


def lookup_revertable_activity_log_entry(
    *,
    activity_log_id: UUID | None,
    scope: ActivityScope,
    item_id: str,
    team_id: int,
    organization_id: Any,
    include_org_scoped: bool,
    user: User | AnonymousUser | None,
    revertable_fields: Iterable[str] | None = None,
) -> ActivityLog:
    """Fetch a single activity log entry, applying the same access controls the
    activity log endpoints apply: team scoping (with org-level activity log opt-in)
    and the user-level visibility restrictions used by ActivityLogViewSet.

    When `activity_log_id` is provided, that entry is returned (or NotFound).

    When `activity_log_id` is None, the most recent entry for this resource that
    has at least one revertable change is returned — this implements the "revert
    my last edit" shortcut that agents typically want. `revertable_fields` must
    be supplied in this case so we can skip entries that touched only fields
    this endpoint doesn't apply (e.g. tag-only updates).

    Raises rest_framework.exceptions.NotFound if no matching entry exists for
    this user — callers do not need to handle the lookup themselves.
    """
    queryset = ActivityLog.objects.filter(scope=scope, item_id=item_id)
    queryset = apply_organization_scoped_filter(queryset, include_org_scoped, team_id, organization_id)
    queryset = apply_activity_visibility_restrictions(queryset, user)

    if activity_log_id is not None:
        try:
            return queryset.get(id=activity_log_id)
        except ActivityLog.DoesNotExist:
            raise exceptions.NotFound("Activity log entry not found for this resource.")

    if revertable_fields is None:
        raise exceptions.ValidationError(
            "Either activity_log_id or revertable_fields must be provided to pick a fallback entry."
        )
    revertable = frozenset(revertable_fields)
    for entry in queryset.order_by("-created_at")[:FALLBACK_LOOKBACK_LIMIT]:
        changes = (entry.detail or {}).get("changes") or []
        if any(c.get("field") in revertable for c in changes):
            return entry
    raise exceptions.NotFound(
        "No recent revertable activity log entry found for this resource. "
        "List entries via activity-log-list and pass an explicit activity_log_id."
    )


def apply_revert_to_instance(
    instance: Model,
    log_entry: ActivityLog,
    revertable_fields: Iterable[str],
) -> tuple[list[str], list[str]]:
    """Apply the `before` value of each captured change in `log_entry` back onto
    `instance`. The caller is responsible for saving the instance afterwards.

    Returns `(applied_fields, skipped_fields)`. A field is applied when its name
    appears in `revertable_fields`; otherwise it is surfaced in `skipped_fields`
    so the caller can communicate what wasn't reverted (typically relations,
    m2m, or immutable metadata that the whitelist deliberately excludes).

    Raises rest_framework.exceptions.ValidationError if the entry has no changes
    to apply, or if every captured change is in the skip list.
    """
    revertable = frozenset(revertable_fields)
    detail = log_entry.detail or {}
    changes = detail.get("changes") or []
    if not changes:
        raise exceptions.ValidationError("Activity log entry has no field changes to revert.")
    applied: list[str] = []
    skipped: list[str] = []
    for change in changes:
        field_name = change.get("field")
        if not field_name:
            continue
        if field_name not in revertable:
            skipped.append(field_name)
            continue
        setattr(instance, field_name, change.get("before"))
        applied.append(field_name)
    if not applied:
        raise exceptions.ValidationError(
            f"None of the recorded changes are revertable through this endpoint. "
            f"Skipped fields: {sorted(set(skipped))}."
        )
    return applied, skipped

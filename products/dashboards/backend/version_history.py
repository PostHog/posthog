"""Dashboard version history reconstruction.

The ``Dashboard`` model already records all field-level changes to the
``ActivityLog`` via ``ModelActivityMixin``. Each entry stores ``before`` and
``after`` values per changed field. To reconstruct a historical state we walk
the log backwards from the current dashboard, undoing each newer entry's
changes until we reach the target version.

The "version" identifier is the ``ActivityLog`` entry's UUID. A revert restores
the dashboard to the state it was in immediately after that log entry was
written (i.e. all newer entries are undone).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import ForeignKey, ManyToManyField, OneToOneField

from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    common_field_exclusions,
    field_exclusions,
)

from products.dashboards.backend.models.dashboard import Dashboard


class VersionNotFound(Exception):
    pass


# Safety cap on the number of activity log entries scanned when walking backwards.
MAX_HISTORY_ENTRIES = 10_000

# Field names that are managed via separate relations and cannot be safely
# round-tripped through the activity log's scalar diff format.
_NON_RECONSTRUCTABLE_RELATIONS = frozenset(
    {
        "tagged_items",
        "tags",
        "tiles",
        "insights",
        "dashboardtile",
        "dashboard_tiles",
        "sharingconfiguration",
        "subscription",
    }
)


def _get_reconstructable_fields() -> frozenset[str]:
    excluded = (
        set(common_field_exclusions)
        | set(field_exclusions.get("Dashboard", []))
        | _NON_RECONSTRUCTABLE_RELATIONS
    )
    # Only restore scalar / JSON fields. FK and M2M values cannot be reliably reapplied from
    # the JSON-encoded activity log payload (the encoder may emit a representation that isn't
    # accepted by ``setattr``), so reverts focus on the dashboard's user-editable scalars.
    return frozenset(
        f.name
        for f in Dashboard._meta.get_fields()
        if f.name not in excluded
        and hasattr(f, "column")
        and not isinstance(f, ForeignKey | OneToOneField | ManyToManyField)
    )


RECONSTRUCTABLE_FIELDS = _get_reconstructable_fields()


def _extract_tracked_fields(dashboard: Dashboard) -> dict[str, Any]:
    return {field: getattr(dashboard, field) for field in RECONSTRUCTABLE_FIELDS}


def _get_target_log(dashboard_id: int, activity_log_id: UUID, team_id: int) -> ActivityLog:
    try:
        return ActivityLog.objects.get(
            id=activity_log_id,
            team_id=team_id,
            scope="Dashboard",
            item_id=str(dashboard_id),
        )
    except ActivityLog.DoesNotExist:
        raise VersionNotFound(f"No dashboard version found for activity log id {activity_log_id}")


def reconstruct_dashboard_at_version(
    dashboard: Dashboard,
    activity_log_id: UUID,
    team_id: int,
) -> dict[str, Any]:
    """Reconstruct the field values for ``dashboard`` as of the given activity log entry.

    Returns a dict of the reconstructable scalar fields plus metadata fields
    (``version_id``, ``version_timestamp``, ``modified_by``, ``is_current``).
    """
    target_log = _get_target_log(dashboard.id, activity_log_id, team_id)
    fields = _extract_tracked_fields(dashboard)

    newer_entries = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="Dashboard",
            item_id=str(dashboard.id),
            activity__in=["updated", "deleted", "restored"],
            created_at__gt=target_log.created_at,
        )
        .order_by("-created_at", "-id")
        .values_list("detail", flat=True)[:MAX_HISTORY_ENTRIES]
        .iterator()
    )

    is_current = True
    for detail in newer_entries:
        is_current = False
        changes = (detail or {}).get("changes") or []
        for change in changes:
            field = change.get("field")
            if field in RECONSTRUCTABLE_FIELDS:
                fields[field] = change.get("before")

    return {
        **fields,
        "version_id": str(target_log.id),
        "version_timestamp": target_log.created_at,
        "modified_by": target_log.user_id,
        "is_current": is_current,
    }


def apply_dashboard_revert(
    dashboard: Dashboard,
    activity_log_id: UUID,
    team_id: int,
) -> dict[str, Any]:
    """Revert ``dashboard`` to the state recorded at ``activity_log_id``.

    Saves the dashboard, which triggers the standard ``ModelActivityMixin``
    activity log entry — that entry will record the revert as a normal update
    (with before/after diffs), preserving full audit history.

    Returns the reconstructed state dict.
    """
    state = reconstruct_dashboard_at_version(dashboard, activity_log_id, team_id)

    if state.get("is_current"):
        # Reverting to the latest recorded state is a no-op; skip the save so we don't
        # log a redundant activity entry.
        return state

    for field in RECONSTRUCTABLE_FIELDS:
        if field in state:
            setattr(dashboard, field, state[field])

    dashboard.save()

    return state


def list_dashboard_versions(
    dashboard_id: int,
    team_id: int,
    limit: int = 50,
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return activity log entries for a dashboard, newest first.

    Each entry is a lightweight dict suitable for rendering a version list.
    """
    qs = ActivityLog.objects.filter(
        team_id=team_id,
        scope="Dashboard",
        item_id=str(dashboard_id),
        activity__in=["created", "updated", "deleted", "restored"],
    ).select_related("user")

    if before is not None:
        qs = qs.filter(created_at__lt=before)

    entries = qs.order_by("-created_at", "-id")[: max(1, min(limit, 200))]

    return [
        {
            "version_id": str(entry.id),
            "created_at": entry.created_at,
            "activity": entry.activity,
            "user": (
                {
                    "id": entry.user.id,
                    "first_name": entry.user.first_name,
                    "last_name": entry.user.last_name,
                    "email": entry.user.email,
                }
                if entry.user_id and entry.user is not None
                else None
            ),
            "is_system": bool(entry.is_system),
            "was_impersonated": bool(entry.was_impersonated),
            "client": entry.client,
            "detail": entry.detail,
        }
        for entry in entries
    ]

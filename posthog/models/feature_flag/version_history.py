from datetime import datetime
from typing import Any

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.feature_flag.feature_flag import FeatureFlag


class VersionNotFound(Exception):
    pass


class VersionHistoryIncomplete(Exception):
    pass


# Fields tracked in the activity log for feature flags.
# Must stay in sync with the fields that changes_between() compares
# (i.e. FeatureFlag model fields minus common_field_exclusions and
# field_exclusions["FeatureFlag"] in activity_log.py).
RECONSTRUCTABLE_FIELDS = frozenset(
    [
        "key",
        "name",
        "filters",
        "active",
        "deleted",
        "version",
        "rollback_conditions",
        "performed_rollback",
        "ensure_experience_continuity",
        "is_remote_configuration",
        "has_encrypted_payloads",
        "evaluation_runtime",
        "bucketing_identifier",
        "has_enriched_analytics",
    ]
)

# Fields that need special accessor logic instead of plain getattr.
_FIELD_ACCESSORS: dict[str, Any] = {
    "filters": lambda flag: flag.get_filters(),
}


def _extract_tracked_fields(flag: FeatureFlag) -> dict[str, Any]:
    return {
        field: _FIELD_ACCESSORS[field](flag) if field in _FIELD_ACCESSORS else getattr(flag, field)
        for field in RECONSTRUCTABLE_FIELDS
    }


def _build_response(
    flag: FeatureFlag,
    fields: dict[str, Any],
    *,
    is_historical: bool,
    version_timestamp: datetime | None,
    modified_by: int | None,
) -> dict[str, Any]:
    return {
        **fields,
        "id": flag.id,
        "created_at": flag.created_at,
        "created_by": flag.created_by_id,
        "is_historical": is_historical,
        "version_timestamp": version_timestamp,
        "modified_by": modified_by,
    }


def _get_version_after(changes: list[dict[str, Any]]) -> int | None:
    """Extract the 'after' value from the version change in an activity log entry."""
    for change in changes:
        if change.get("field") == "version":
            return change.get("after")
    return None


def reconstruct_flag_at_version(
    flag: FeatureFlag,
    target_version: int,
    team_id: int,
) -> dict[str, Any]:
    """
    Reconstruct a feature flag's state at a given version by working
    backward from the current state using the activity log.

    Returns a dict of field values representing the flag at that version.

    Raises VersionNotFound if the version is out of range.
    Raises VersionHistoryIncomplete if activity log entries are missing.
    """
    current_version = flag.version
    if current_version is None:
        raise VersionHistoryIncomplete("Flag has no version set")

    if target_version < 1 or target_version > current_version:
        raise VersionNotFound(f"Version {target_version} not found (current version is {current_version})")

    fields = _extract_tracked_fields(flag)

    if target_version == current_version:
        return _build_response(
            flag,
            fields,
            is_historical=False,
            version_timestamp=flag.updated_at or flag.created_at,
            modified_by=flag.last_modified_by_id,
        )

    # Fetch activity log entries that bump the version, newest first, streaming
    # with .iterator() so we stop reading from the DB once we reach the target.
    # Soft-delete and restore also bump the version but are logged as "deleted"
    # and "restored" rather than "updated".
    entries = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="FeatureFlag",
            item_id=str(flag.id),
            activity__in=["updated", "deleted", "restored"],
        )
        .order_by("-created_at", "-id")
        .values_list("detail", "created_at", "user_id")
        .iterator()
    )

    # Walk backwards, undoing changes until we reach the target version.
    # Each entry with version_after > target_version needs to be undone.
    # The entry with version_after == target_version created our target — use its metadata.
    version_timestamp = None
    modified_by = None
    reached_target = False

    for detail, created_at, user_id in entries:
        changes = (detail or {}).get("changes") or []
        version_after = _get_version_after(changes)

        if version_after is None:
            continue

        if version_after == target_version:
            version_timestamp = created_at
            modified_by = user_id
            reached_target = True
            break

        if version_after > target_version:
            for change in changes:
                field = change.get("field")
                if field and field in RECONSTRUCTABLE_FIELDS:
                    fields[field] = change.get("before")

    if not reached_target:
        if target_version == 1:
            # Version 1 is the creation — no activity log entry transitions "into" it.
            # We've undone all entries, so fields now represent the creation state.
            version_timestamp = flag.created_at
            modified_by = flag.created_by_id
        else:
            raise VersionHistoryIncomplete(f"Activity log is incomplete. Cannot reconstruct version {target_version}.")

    return _build_response(
        flag,
        fields,
        is_historical=True,
        version_timestamp=version_timestamp,
        modified_by=modified_by,
    )

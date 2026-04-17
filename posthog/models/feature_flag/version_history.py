from datetime import datetime
from typing import Any

from posthog.models.activity_logging.activity_log import ActivityLog, common_field_exclusions, field_exclusions
from posthog.models.feature_flag.feature_flag import FeatureFlag


class VersionNotFound(Exception):
    pass


class VersionHistoryIncomplete(Exception):
    pass


def _get_reconstructable_fields() -> frozenset[str]:
    """Derive tracked fields dynamically so new FeatureFlag fields are picked up automatically."""
    excluded = set(common_field_exclusions) | set(field_exclusions.get("FeatureFlag", []))
    return frozenset(f.name for f in FeatureFlag._meta.get_fields() if f.name not in excluded and hasattr(f, "column"))


RECONSTRUCTABLE_FIELDS = _get_reconstructable_fields()

# Safety cap on the number of activity log entries scanned when walking backwards.
# In normal use we stop early once we reach the target version; this bound protects
# against unbounded scans if the activity log is malformed or much larger than expected.
MAX_HISTORY_ENTRIES = 10_000

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
        .values_list("detail", "created_at", "user_id")[:MAX_HISTORY_ENTRIES]
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
        elif version_after < target_version:
            # Entries are newest-first; falling below the target means its entry is missing.
            break

    if not reached_target:
        if target_version == 1:
            # Version 1 is the creation — no activity log entry transitions "into" it.
            # We've undone all entries, so fields now represent the creation state.
            version_timestamp = flag.created_at
            modified_by = flag.created_by_id
        else:
            raise VersionHistoryIncomplete(f"Activity log is incomplete. Cannot reconstruct version {target_version}.")

    # Historical activity log entries may store filters in legacy shapes
    # (None, {}, or missing "groups"). Normalize so the response shape is
    # predictable for API consumers.
    raw_filters = fields.get("filters")
    if not raw_filters:
        fields["filters"] = {"groups": []}
    elif "groups" not in raw_filters:
        fields["filters"] = {**raw_filters, "groups": []}

    return _build_response(
        flag,
        fields,
        is_historical=True,
        version_timestamp=version_timestamp,
        modified_by=modified_by,
    )


def find_version_at_timestamp(flag: FeatureFlag, timestamp: datetime, team_id: int) -> int | None:
    """
    Find the appropriate version number for a feature flag at a given timestamp.

    Returns the version that was active at the specified timestamp, or None if
    the flag didn't exist at that time.

    A flag is considered non-existent if:
    - The timestamp is before the flag's creation
    - The flag was soft-deleted at or before the timestamp (without subsequent restoration)

    This ensures historical evaluation treats soft-deleted flags consistently
    with flags that never existed at the given time.
    """
    if not flag.version:
        return None

    # If timestamp is before flag creation, flag didn't exist
    if timestamp < flag.created_at:
        return None

    # We need to check the activity log to see if there were any deletions/restorations
    # that happened between the flag's last update and the query timestamp
    # We can't just return the current version when timestamp >= updated_at because
    # there might be soft-delete operations recorded in the activity log after updated_at

    # Get activity log entries at or before the timestamp, streaming with .iterator()
    # to avoid loading all entries into memory. We need to check both deletion state
    # and find the most recent entry that contains version information.
    entries = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="FeatureFlag",
            item_id=str(flag.id),
            activity__in=["updated", "deleted", "restored"],
            created_at__lte=timestamp,  # Only entries at or before the timestamp
        )
        .order_by("-created_at", "-id")  # Most recent first
        .values_list("activity", "detail", flat=False)[:MAX_HISTORY_ENTRIES]
        .iterator()
    )

    # Track deletion state and find the most recent version information
    # We need to determine the net state: was the flag deleted at this timestamp?
    # Process entries in chronological order to track state changes
    most_recent_version = None
    flag_was_deleted = False

    # Process entries in reverse order (oldest first) to track state transitions
    entries_list = list(entries)
    for activity, detail in reversed(entries_list):
        # Extract version information from this entry first
        changes = (detail or {}).get("changes") or []
        version_after = _get_version_after(changes)

        # Only consider entries that have version information
        # Bulk delete entries without version changes should be skipped
        if version_after is not None:
            most_recent_version = version_after

            # Track the deletion/restoration state transitions only for versioned entries
            if activity == "deleted":
                flag_was_deleted = True
            elif activity == "restored":
                flag_was_deleted = False

    # If flag was in a deleted state at the timestamp, treat as non-existent
    if flag_was_deleted:
        return None

    # If we found version information and flag wasn't deleted, return the version
    if most_recent_version is not None:
        return most_recent_version

    # If we found no version changes but timestamp is after the flag's last update,
    # return the current version (unless flag was deleted)
    if timestamp >= (flag.updated_at or flag.created_at):
        return flag.version

    # If we found no version changes, the flag was at version 1 (creation)
    return 1


def reconstruct_flag_at_timestamp(
    flag: FeatureFlag,
    timestamp: datetime,
    team_id: int,
) -> dict[str, Any]:
    """
    Reconstruct a feature flag's state at a given timestamp.

    This is a convenience wrapper around find_version_at_timestamp + reconstruct_flag_at_version
    to avoid duplicating database queries and logic.
    """
    # Find the version that was active at the timestamp
    target_version = find_version_at_timestamp(flag, timestamp, team_id)

    if target_version is None:
        raise VersionNotFound(f"Flag did not exist at {timestamp} (created at {flag.created_at})")

    # Use the existing reconstruction logic
    return reconstruct_flag_at_version(flag, target_version, team_id)

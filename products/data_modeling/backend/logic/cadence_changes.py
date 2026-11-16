"""Shared bookkeeping for writes to a saved query's cadence, used by every surface that makes one."""

from datetime import timedelta
from uuid import UUID

from posthog.models.activity_logging.activity_log import Change

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def clear_legacy_sync_interval(team_id: int, saved_query_id: UUID) -> None:
    """Drop the saved query's own interval, which the node target replaces on tiered teams.

    The node target is the only store of frequency intent. A stale interval left in the column would
    answer for a cadence the user just set or cleared, so every cadence write clears it. A caller
    holding the row must also clear its in-memory copy before serializing it.
    """
    DataWarehouseSavedQuery.objects.filter(team_id=team_id, pk=saved_query_id).update(sync_frequency_interval=None)


def cadence_changes(
    targets: tuple[timedelta | None, timedelta | None], pins: tuple[bool, bool] | None = None
) -> list[Change]:
    """The activity log entries for a cadence write, one per field that changed.

    The cadence lives on the DAG node, so `changes_between()` on the saved query sees nothing. Every
    cadence writer builds its entries here so the fields read alike in the activity log.
    """

    def render(target: timedelta | None) -> str | None:
        return str(target) if target is not None else None

    fields: list[tuple[str, str | bool | None, str | bool | None]] = [
        ("sync_frequency_interval", render(targets[0]), render(targets[1]))
    ]
    if pins is not None:
        fields.append(("sync_frequency_pinned", pins[0], pins[1]))
    return [
        Change(type="DataWarehouseSavedQuery", action="changed", field=field, before=before, after=after)
        for field, before, after in fields
        if before != after
    ]

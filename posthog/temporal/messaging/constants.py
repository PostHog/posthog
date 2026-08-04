"""Shared constants for temporal messaging workflows."""

# precalculated_events.source prefix written by the event backfill (as opposed to the
# realtime consumer, which writes a "cohort_filter_" prefix). Shared so the day-already-
# backfilled check and the backfill writer can't drift apart.
BACKFILL_EVENT_SOURCE_PREFIX = "cohort_event_backfill"

CHILD_WORKFLOW_ID_SUFFIX = "child"


def get_child_workflow_id(parent_workflow_id: str, child_index: int) -> str:
    """Generate a standardized child workflow ID."""
    return f"{parent_workflow_id}-{CHILD_WORKFLOW_ID_SUFFIX}-{child_index}"


def get_percentile_bucket_label(min_percentile: float | None, max_percentile: float | None) -> str:
    """Generate percentile bucket label for metrics from min/max percentile values."""
    if min_percentile is None and max_percentile is None:
        return "manual"
    elif min_percentile is None:
        return f"p0-p{int(max_percentile) if max_percentile is not None else 0}"
    elif max_percentile is None:
        return f"p{int(min_percentile) if min_percentile is not None else 0}-p100"
    else:
        return f"p{int(min_percentile)}-p{int(max_percentile)}"

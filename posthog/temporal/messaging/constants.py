"""Shared constants for temporal messaging workflows."""

# Workflow IDs and patterns
REALTIME_COHORT_CALCULATION_SCHEDULE_ID = "realtime-cohort-calculation-schedule"
REALTIME_COHORT_CALCULATION_COORDINATOR_WORKFLOW_NAME = "realtime-cohort-calculation-coordinator"
CHILD_WORKFLOW_ID_SUFFIX = "child"

# Duration percentile-based schedule IDs
REALTIME_COHORT_CALCULATION_P0_P50_SCHEDULE_ID = "realtime-cohort-calculation-p0-p50"
REALTIME_COHORT_CALCULATION_P50_P80_SCHEDULE_ID = "realtime-cohort-calculation-p50-p80"
REALTIME_COHORT_CALCULATION_P80_P90_SCHEDULE_ID = "realtime-cohort-calculation-p80-p90"
REALTIME_COHORT_CALCULATION_P90_P95_SCHEDULE_ID = "realtime-cohort-calculation-p90-p95"
REALTIME_COHORT_CALCULATION_P95_P99_SCHEDULE_ID = "realtime-cohort-calculation-p95-p99"
REALTIME_COHORT_CALCULATION_P99_P100_SCHEDULE_ID = "realtime-cohort-calculation-p99-p100"


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

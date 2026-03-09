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
REALTIME_COHORT_CALCULATION_P95_P100_SCHEDULE_ID = "realtime-cohort-calculation-p95-p100"


def get_child_workflow_id(parent_workflow_id: str, child_index: int) -> str:
    """Generate a standardized child workflow ID."""
    return f"{parent_workflow_id}-{CHILD_WORKFLOW_ID_SUFFIX}-{child_index}"

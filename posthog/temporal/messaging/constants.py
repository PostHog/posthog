"""Shared constants for temporal messaging workflows."""

# Workflow IDs and patterns
REALTIME_COHORT_CALCULATION_SCHEDULE_ID = "realtime-cohort-calculation-schedule"
REALTIME_COHORT_CALCULATION_COORDINATOR_WORKFLOW_NAME = "realtime-cohort-calculation-coordinator"
CHILD_WORKFLOW_ID_SUFFIX = "child"


def get_child_workflow_id(parent_workflow_id: str, child_index: int) -> str:
    """Generate a standardized child workflow ID."""
    return f"{parent_workflow_id}-{CHILD_WORKFLOW_ID_SUFFIX}-{child_index}"

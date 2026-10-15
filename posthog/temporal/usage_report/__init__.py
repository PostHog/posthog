from posthog.temporal.usage_report.activities import (
    aggregate_and_chunk_org_reports,
    cleanup_intermediates,
    enqueue_pointer_message,
    fetch_usage_counter_report,
    plan_usage_counters,
    run_legacy_usage_counter,
    run_query_to_s3,
)
from posthog.temporal.usage_report.workflow import RunUsageReportsWorkflow

WORKFLOWS = [
    RunUsageReportsWorkflow,
]

AGGREGATION_ACTIVITIES = [aggregate_and_chunk_org_reports]

ACTIVITIES = [
    plan_usage_counters,
    fetch_usage_counter_report,
    run_legacy_usage_counter,
    run_query_to_s3,
    # Existing workflow histories can still have aggregation scheduled on the billing queue.
    *AGGREGATION_ACTIVITIES,
    enqueue_pointer_message,
    cleanup_intermediates,
]

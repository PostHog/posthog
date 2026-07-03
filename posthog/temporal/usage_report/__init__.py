from posthog.temporal.usage_report.activities import (
    aggregate_and_chunk_org_reports,
    cleanup_intermediates,
    enqueue_pointer_message,
    run_query_to_s3,
)
from posthog.temporal.usage_report.backtest import (
    BacktestUsageReportsWorkflow,
    diff_backtest,
    find_backtest_baseline,
    run_backtest_candidate,
)
from posthog.temporal.usage_report.workflow import RunUsageReportsWorkflow

WORKFLOWS = [
    RunUsageReportsWorkflow,
    BacktestUsageReportsWorkflow,
]

ACTIVITIES = [
    run_query_to_s3,
    aggregate_and_chunk_org_reports,
    enqueue_pointer_message,
    cleanup_intermediates,
    find_backtest_baseline,
    run_backtest_candidate,
    diff_backtest,
]

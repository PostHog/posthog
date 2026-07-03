"""Metric helpers for the usage-reports v2 sender pipeline.

Everything records through the Temporal SDK metric meter (see
`posthog.temporal.common.metrics.get_metric_meter`), so these series ride the
worker's combined Prometheus endpoint alongside the built-in `temporal_*`
metrics. Billing consumes the matching receiver-side metrics
(`billing_sqs_usage_reports_v2_*` / `billing_temporal_usage_reports_v2_*`);
together they back the "Usage Reports v2" Grafana dashboard.
"""

import time
from datetime import timedelta

from temporalio.common import MetricCounter

from posthog.temporal.common.metrics import get_metric_meter

USAGE_REPORTS_QUERY_LATENCY = "usage_reports_v2_query_latency"
USAGE_REPORTS_AGGREGATE_LATENCY = "usage_reports_v2_aggregate_latency"
USAGE_REPORTS_ENQUEUE_LATENCY = "usage_reports_v2_enqueue_latency"
USAGE_REPORTS_WORKFLOW_LATENCY = "usage_reports_v2_workflow_latency"

# Registered with `histogram_bucket_overrides` in
# `posthog.temporal.common.worker`: gather queries run up to 30 minutes,
# aggregation up to an hour, and the whole workflow can span a few hours —
# far beyond the SDK's default (sub-minute) buckets.
USAGE_REPORTS_LATENCY_HISTOGRAM_METRICS = (
    USAGE_REPORTS_QUERY_LATENCY,
    USAGE_REPORTS_AGGREGATE_LATENCY,
    USAGE_REPORTS_ENQUEUE_LATENCY,
    USAGE_REPORTS_WORKFLOW_LATENCY,
)
USAGE_REPORTS_LATENCY_HISTOGRAM_BUCKETS = [
    100.0,  # 100ms
    500.0,  # 500ms
    1_000.0,  # 1s
    5_000.0,  # 5s
    15_000.0,  # 15s
    30_000.0,  # 30s
    60_000.0,  # 1m
    120_000.0,  # 2m
    300_000.0,  # 5m
    600_000.0,  # 10m
    900_000.0,  # 15m
    1_800_000.0,  # 30m
    3_600_000.0,  # 1h
    7_200_000.0,  # 2h
    14_400_000.0,  # 4h
]


def get_workflow_finished_metric(status: str) -> MetricCounter:
    return get_metric_meter({"status": status}).create_counter(
        "usage_reports_v2_workflow_finished",
        "Number of usage-reports v2 workflow runs finished, for any reason (including failure).",
    )


def record_workflow_latency(delta: timedelta, status: str) -> None:
    get_metric_meter({"status": status}).create_histogram_timedelta(
        USAGE_REPORTS_WORKFLOW_LATENCY,
        "End-to-end wall-clock duration of one usage-reports v2 workflow run.",
        unit="ms",
    ).record(delta)


def get_pointer_messages_sent_metric(outcome: str) -> MetricCounter:
    return get_metric_meter({"outcome": outcome}).create_counter(
        "usage_reports_v2_pointer_messages_sent",
        "SQS pointer messages handed to billing, by outcome (sent / skipped_no_ee).",
    )


def record_aggregate_output(total_orgs: int, total_orgs_with_usage: int, chunk_count: int) -> None:
    """Record the last-run volume gauges.

    Called from the enqueue activity (not aggregation) so the whole last-run
    snapshot — volumes and sent-timestamp — is written by the same worker pod,
    and only for runs that actually handed a pointer to billing.
    """
    meter = get_metric_meter()
    meter.create_gauge(
        "usage_reports_v2_orgs_considered",
        "Organizations considered by the last usage-reports v2 run.",
    ).set(total_orgs)
    meter.create_gauge(
        "usage_reports_v2_orgs_with_usage",
        "Organizations with non-zero usage reported by the last usage-reports v2 run.",
    ).set(total_orgs_with_usage)
    meter.create_gauge(
        "usage_reports_v2_chunks_written",
        "JSONL chunks uploaded to S3 by the last usage-reports v2 run.",
    ).set(chunk_count)


def record_pointer_sent_timestamp() -> None:
    """Stamp the wall-clock time of the last successful SQS pointer send.

    Dashboards read this as `time() - max_over_time(...)` to alert on a
    missed run, so it must only be set after the send succeeded.
    """
    get_metric_meter().create_gauge_float(
        "usage_reports_v2_last_pointer_sent_timestamp_seconds",
        "Unix timestamp of the last successfully sent usage-reports v2 SQS pointer.",
    ).set(time.time())

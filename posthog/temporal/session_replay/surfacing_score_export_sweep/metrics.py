"""Tick-level metrics for the surfacing score export sweep.

The workflow gathers partition results with return_exceptions=True and summarizes rather than raising, so a
tick where every partition fails still completes successfully. These counters make that visible: without
them a total failure is only a log line, and the workflow's success hides it from any dashboard or alert.
"""

from posthog.temporal.ai_observability.metrics import get_metric_meter

PARTITIONS_DISPATCHED_COUNTER = "surfacing_score_export_partitions_dispatched"
PARTITIONS_DISPATCHED_DESCRIPTION = "Partitions dispatched for export in a surfacing score export sweep tick"

PARTITIONS_FAILED_COUNTER = "surfacing_score_export_partitions_failed"
PARTITIONS_FAILED_DESCRIPTION = "Partitions that failed to export in a surfacing score export sweep tick"

ROWS_EXPORTED_COUNTER = "surfacing_score_export_rows_exported"
ROWS_EXPORTED_DESCRIPTION = "Score rows exported in a surfacing score export sweep tick"

TICKS_ALL_FAILED_COUNTER = "surfacing_score_export_ticks_all_failed"
TICKS_ALL_FAILED_DESCRIPTION = (
    "Sweep ticks where every dispatched partition failed yet the workflow still completed successfully"
)


def record_tick_summary(*, partitions_dispatched: int, partitions_failed: int, total_rows: int) -> None:
    if partitions_dispatched <= 0:
        return
    meter = get_metric_meter()
    meter.create_counter(PARTITIONS_DISPATCHED_COUNTER, PARTITIONS_DISPATCHED_DESCRIPTION).add(partitions_dispatched)
    if partitions_failed > 0:
        meter.create_counter(PARTITIONS_FAILED_COUNTER, PARTITIONS_FAILED_DESCRIPTION).add(partitions_failed)
    if total_rows > 0:
        meter.create_counter(ROWS_EXPORTED_COUNTER, ROWS_EXPORTED_DESCRIPTION).add(total_rows)
    if partitions_failed >= partitions_dispatched:
        meter.create_counter(TICKS_ALL_FAILED_COUNTER, TICKS_ALL_FAILED_DESCRIPTION).add(1)

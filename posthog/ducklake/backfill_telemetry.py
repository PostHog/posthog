from datetime import date

from posthog.ph_client import ph_scoped_capture

BACKFILL_PARTITION_EVENT = "warehouse_event_backfill_partition"
BACKFILL_DISTINCT_ID = "warehouse-event-backfill"


def emit_backfill_partition_event(
    *,
    partition_date: date,
    status: str,
    run_id: str,
    rows_exported: int | None = None,
    files_exported: int | None = None,
    files_registered: int | None = None,
    error_message: str | None = None,
) -> None:
    """Capture one terminal event per backfill partition run. Best-effort: on Cloud the event
    lands in the internal project; off Cloud `ph_scoped_capture` is a no-op."""
    properties: dict[str, object] = {
        "partition_date": partition_date.isoformat(),
        "status": status,
        "run_id": run_id,
        "rows_exported": rows_exported,
        "files_exported": files_exported,
        "files_registered": files_registered,
        "error_message": error_message,
    }
    with ph_scoped_capture() as capture:
        capture(distinct_id=BACKFILL_DISTINCT_ID, event=BACKFILL_PARTITION_EVENT, properties=properties)

from datetime import date

from posthog.ph_client import ph_scoped_capture

# One capture event per duckling backfill partition run, emitted to the internal telemetry project.
# Carries the customer team_id as a property so the warehouse freshness API can report per team.
BACKFILL_PARTITION_EVENT = "warehouse_event_backfill_partition"
BACKFILL_DISTINCT_ID = "warehouse-event-backfill"


def emit_backfill_partition_event(
    *,
    team_id: int,
    partition_date: date,
    status: str,
    run_id: str,
    files_exported: int | None = None,
    files_registered: int | None = None,
    dates_processed: int | None = None,
    error_message: str | None = None,
) -> None:
    """Capture one terminal event per backfill partition run (status: "success" | "failed").

    Best-effort: on Cloud the event lands in the internal project; off Cloud `ph_scoped_capture`
    is a no-op. `partition_date` is the most recent day the partition covers (the freshness edge).
    """
    properties: dict[str, object] = {
        "team_id": team_id,
        "partition_date": partition_date.isoformat(),
        "status": status,
        "run_id": run_id,
        "files_exported": files_exported,
        "files_registered": files_registered,
        "dates_processed": dates_processed,
        "error_message": error_message,
    }
    with ph_scoped_capture() as capture:
        capture(distinct_id=BACKFILL_DISTINCT_ID, event=BACKFILL_PARTITION_EVENT, properties=properties)

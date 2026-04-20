import logging
import datetime as dt
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import MetricCounter

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp

if TYPE_CHECKING:
    from products.data_warehouse.backend.models.external_data_job import ExternalDataJob

logger = logging.getLogger(__name__)


DATA_IMPORT_APP_SOURCE = "warehouse_source_sync"

_TERMINAL_STATUS_TO_METRIC: dict[str, tuple[str, str]] = {
    "Completed": ("success", "succeeded"),
    "Failed": ("failure", "failed"),
    "BillingLimitReached": ("failure", "billing_limited"),
    "BillingLimitTooLow": ("failure", "billing_limited"),
}

# Shared source of truth for which ExternalDataJob statuses are terminal — also
# imported by update_external_job_status to gate finished_at stamping and metric
# emission on the first terminal transition.
TERMINAL_JOB_STATUSES: frozenset[str] = frozenset(_TERMINAL_STATUS_TO_METRIC)


def get_data_import_finished_metric(source_type: str | None, status: str) -> MetricCounter:
    source_type = source_type or "unknown"
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type, "status": status})
        .create_counter("data_import_finished", "Number of data imports finished, for any reason (including failure).")
    )


def emit_data_import_app_metrics(job: "ExternalDataJob") -> None:
    """Emit app_metrics2 rows for a data import job that just reached terminal state.

    Writes best-effort messages to the app_metrics2 Kafka topic — failures are
    logged but never raised, so a broken metrics path cannot surface as a
    pipeline failure. Runs that are not in a terminal status are a no-op.
    """
    kind_name = _TERMINAL_STATUS_TO_METRIC.get(job.status)
    if kind_name is None:
        return

    metric_kind, metric_name = kind_name
    finished_at = job.finished_at or dt.datetime.now(dt.UTC)
    timestamp = format_clickhouse_timestamp(finished_at)

    common_fields = {
        "team_id": job.team_id,
        "app_source": DATA_IMPORT_APP_SOURCE,
        "app_source_id": str(job.pipeline_id),
        "instance_id": str(job.schema_id) if job.schema_id else "",
        "timestamp": timestamp,
    }

    payloads: list[dict] = [
        {
            **common_fields,
            "metric_kind": metric_kind,
            "metric_name": metric_name,
            "count": 1,
        }
    ]

    if job.rows_synced and job.rows_synced > 0:
        payloads.append(
            {
                **common_fields,
                "metric_kind": "rows",
                "metric_name": "rows_synced",
                "count": job.rows_synced,
            }
        )

    try:
        producer = KafkaProducer()
        for payload in payloads:
            producer.produce(topic=KAFKA_APP_METRICS2, data=payload)
    except Exception:
        logger.exception("Failed to emit data import app_metrics2 rows")

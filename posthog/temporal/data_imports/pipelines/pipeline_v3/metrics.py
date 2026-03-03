from temporalio import activity
from temporalio.common import MetricCounter, MetricHistogramFloat


def get_rows_extracted_metric(team_id: str, schema_id: str, source_type: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"team_id": team_id, "schema_id": schema_id, "source_type": source_type})
        .create_counter("warehouse_producer_rows_extracted_total", "Total rows extracted by the producer")
    )


def get_batches_produced_metric(team_id: str, schema_id: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"team_id": team_id, "schema_id": schema_id})
        .create_counter("warehouse_producer_batches_produced_total", "Total batches produced")
    )


def get_s3_write_duration_metric() -> MetricHistogramFloat:
    return activity.metric_meter().create_histogram_float(
        "warehouse_producer_s3_write_duration_seconds", "Duration of S3 batch writes", "s"
    )


def get_s3_write_errors_metric(error_type: str) -> MetricCounter:
    return (
        activity.metric_meter()
        .with_additional_attributes({"error_type": error_type})
        .create_counter("warehouse_producer_s3_write_errors_total", "Total S3 write errors")
    )


def get_kafka_flush_failures_metric() -> MetricCounter:
    return activity.metric_meter().create_counter(
        "warehouse_producer_kafka_flush_failures_total", "Total Kafka flush failures"
    )


def get_pipeline_run_duration_metric(
    team_id: str, source_type: str, sync_type: str, status: str
) -> MetricHistogramFloat:
    return (
        activity.metric_meter()
        .with_additional_attributes(
            {"team_id": team_id, "source_type": source_type, "sync_type": sync_type, "status": status}
        )
        .create_histogram_float("warehouse_pipeline_run_duration_seconds", "Duration of full pipeline runs", "s")
    )

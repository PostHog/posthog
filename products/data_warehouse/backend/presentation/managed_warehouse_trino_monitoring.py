from collections.abc import Mapping
from typing import cast

from rest_framework import serializers

from products.data_warehouse.backend.presentation.managed_warehouse_monitoring import (
    MANAGED_WAREHOUSE_MONITORING_WINDOWS,
    ManagedWarehouseMonitoringSeriesResponseSerializer,
    ManagedWarehouseMonitoringUpstreamError,
    serialize_monitoring_response,
)

MANAGED_WAREHOUSE_TRINO_MONITORING_METRICS = (
    "queries_in_flight",
    "query_rate",
    "error_ratio",
    "duration_p50",
    "duration_p95",
    "queue_time_p95",
    "scanned_bytes_rate",
    "cpu_seconds_rate",
    "storage_bytes",
)
MANAGED_WAREHOUSE_TRINO_MONITORING_LABELS = {
    "queries_in_flight": frozenset({"state"}),
    "query_rate": frozenset({"status", "error_type"}),
    "error_ratio": frozenset(),
    "duration_p50": frozenset(),
    "duration_p95": frozenset(),
    "queue_time_p95": frozenset(),
    "scanned_bytes_rate": frozenset(),
    "cpu_seconds_rate": frozenset(),
    "storage_bytes": frozenset(),
}


class ManagedWarehouseTrinoMonitoringStateSerializer(serializers.Serializer):
    state = serializers.CharField(
        help_text="Trino lifecycle state for the organization: not_enabled, pending, provisioning, ready, or failed."
    )
    ready_at = serializers.DateTimeField(
        allow_null=True, help_text="UTC timestamp when Trino became ready for the organization, or null."
    )
    failed_at = serializers.DateTimeField(
        allow_null=True, help_text="UTC timestamp when Trino setup last failed for the organization, or null."
    )


class ManagedWarehouseTrinoMonitoringLimitsSerializer(serializers.Serializer):
    max_running_queries = serializers.IntegerField(
        min_value=0,
        help_text="Maximum number of the organization's queries that run at the same time. Zero when Trino is not enabled.",
    )
    max_queued_queries = serializers.IntegerField(
        min_value=0,
        help_text="Maximum number of the organization's queries that can wait in the queue. Zero when Trino is not enabled.",
    )


class ManagedWarehouseTrinoMonitoringTotalsSerializer(serializers.Serializer):
    in_flight = serializers.IntegerField(
        min_value=0, help_text="Queries submitted and not yet finished. Equals running plus queued."
    )
    running = serializers.IntegerField(
        min_value=0,
        help_text="In-flight queries past the queue. This is the count the concurrency limit applies to.",
    )
    queued = serializers.IntegerField(min_value=0, help_text="Queries waiting for a running slot.")
    blocked = serializers.IntegerField(
        min_value=0,
        help_text="Running queries whose work is all waiting on data or metadata. A subset of running.",
    )
    longest_running_ms = serializers.IntegerField(
        min_value=0, help_text="Elapsed milliseconds of the longest in-flight query, or zero when there is none."
    )
    physical_input_bytes = serializers.IntegerField(
        min_value=0, help_text="Bytes read so far by all in-flight queries."
    )


class ManagedWarehouseTrinoMonitoringQuerySerializer(serializers.Serializer):
    query_id = serializers.CharField(help_text="Trino query identifier.")
    state = serializers.CharField(
        help_text="Trino query state in lower case, such as queued, planning, starting, running, or finishing."
    )
    user = serializers.CharField(
        allow_blank=True, help_text="Warehouse username that ran the query. Blank when it cannot be resolved."
    )
    source = serializers.CharField(  # type: ignore[assignment]  # Response field shadows DRF's source option.
        allow_blank=True, help_text="Client-reported source of the query, such as a tool name. Blank when not set."
    )
    query = serializers.CharField(
        allow_blank=True,
        help_text="SQL text with literal values replaced by ? and comments removed. A placeholder when unavailable.",
    )
    created_at = serializers.DateTimeField(
        allow_null=True, help_text="UTC timestamp when the query was submitted, or null when Trino does not report it."
    )
    elapsed_ms = serializers.IntegerField(min_value=0, help_text="Milliseconds since the query was submitted.")
    queued_ms = serializers.IntegerField(min_value=0, help_text="Milliseconds the query spent queued.")
    cpu_ms = serializers.IntegerField(min_value=0, help_text="CPU milliseconds the query has used.")
    physical_input_bytes = serializers.IntegerField(min_value=0, help_text="Bytes the query has read from storage.")
    peak_memory_bytes = serializers.IntegerField(min_value=0, help_text="Peak memory the query has reserved, in bytes.")
    processed_input_rows = serializers.IntegerField(min_value=0, help_text="Rows the query has read.")
    progress_percentage = serializers.FloatField(
        min_value=0,
        allow_null=True,
        help_text="Best-effort progress percentage, or null when Trino cannot estimate it.",
    )
    blocked = serializers.BooleanField(help_text="Whether all of the query's work is waiting on data or metadata.")


class ManagedWarehouseTrinoMonitoringSnapshotResponseSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(
        min_value=1, max_value=1, help_text="Version of the Trino monitoring response schema."
    )
    org_id = serializers.CharField(help_text="Organization whose managed warehouse is represented.")
    as_of = serializers.DateTimeField(help_text="UTC timestamp when this snapshot was assembled.")
    trino = ManagedWarehouseTrinoMonitoringStateSerializer(help_text="Trino lifecycle details for the organization.")
    available = serializers.BooleanField(
        help_text="Whether live query data could be read. When false, totals are zero and do not mean the warehouse is idle."
    )
    limits = ManagedWarehouseTrinoMonitoringLimitsSerializer(help_text="Concurrency and queue limits.")
    totals = ManagedWarehouseTrinoMonitoringTotalsSerializer(help_text="Current in-flight query totals.")
    queries = ManagedWarehouseTrinoMonitoringQuerySerializer(
        many=True, help_text="In-flight queries, longest-running first, capped at 200 rows."
    )
    queries_truncated = serializers.BooleanField(
        help_text="Whether the query list was capped. Totals always cover every in-flight query."
    )


class ManagedWarehouseTrinoMonitoringSeriesQuerySerializer(serializers.Serializer):
    metric = serializers.ChoiceField(
        choices=MANAGED_WAREHOUSE_TRINO_MONITORING_METRICS,
        help_text="Allow-listed Trino metric to retrieve.",
    )
    window = serializers.ChoiceField(
        choices=MANAGED_WAREHOUSE_MONITORING_WINDOWS,
        default="24h",
        help_text="Trailing time window to retrieve. Defaults to 24h.",
    )


def serialize_trino_monitoring_snapshot(raw: object, *, expected_organization_id: str) -> dict[str, object]:
    return serialize_monitoring_response(
        raw,
        serializer_class=ManagedWarehouseTrinoMonitoringSnapshotResponseSerializer,
        expected_organization_id=expected_organization_id,
    )


def serialize_trino_monitoring_series(
    raw: object,
    *,
    expected_organization_id: str,
    expected_metric: str,
) -> dict[str, object]:
    data = serialize_monitoring_response(
        raw,
        serializer_class=ManagedWarehouseMonitoringSeriesResponseSerializer,
        expected_organization_id=expected_organization_id,
    )
    if data["metric"] != expected_metric:
        raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned a different metric")
    allowed_labels = MANAGED_WAREHOUSE_TRINO_MONITORING_LABELS[expected_metric]
    for series in cast(list[object], data["series"]):
        if not isinstance(series, Mapping) or not isinstance(series.get("labels"), Mapping):
            raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned invalid series labels")
        if not set(series["labels"]).issubset(allowed_labels):
            raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned unexpected series labels")
    return data

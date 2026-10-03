from collections.abc import Mapping
from typing import cast

from rest_framework import serializers

MANAGED_WAREHOUSE_MONITORING_METRICS = (
    "query_rate",
    "error_ratio",
    "duration_p50",
    "duration_p95",
    "sessions_active",
    "acquire_p95",
    "acquire_by_source",
    "storage_bytes",
    "worker_crash_rate",
)
MANAGED_WAREHOUSE_MONITORING_WINDOWS = ("1h", "6h", "24h", "7d", "30d")
MANAGED_WAREHOUSE_MONITORING_LABELS = {
    "query_rate": frozenset({"status", "reason"}),
    "error_ratio": frozenset(),
    "duration_p50": frozenset(),
    "duration_p95": frozenset(),
    "sessions_active": frozenset(),
    "acquire_p95": frozenset({"source"}),
    "acquire_by_source": frozenset({"source"}),
    "storage_bytes": frozenset(),
    "worker_crash_rate": frozenset(),
}


class ManagedWarehouseMonitoringUpstreamError(Exception):
    pass


class ManagedWarehouseMonitoringErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(required=False, help_text="Human-readable managed warehouse monitoring error.")
    type = serializers.CharField(required=False, help_text="Machine-readable validation error type.")
    code = serializers.CharField(required=False, help_text="Machine-readable validation error code.")
    detail = serializers.CharField(required=False, help_text="Human-readable validation error detail.")
    attr = serializers.CharField(required=False, allow_null=True, help_text="Query parameter associated with an error.")


class ManagedWarehouseMonitoringWarehouseSerializer(serializers.Serializer):
    state = serializers.CharField(
        help_text="Current managed warehouse lifecycle state, such as ready, provisioning, or resharding."
    )


class ManagedWarehouseMonitoringLimitsSerializer(serializers.Serializer):
    max_workers = serializers.IntegerField(
        min_value=0,
        help_text="Maximum concurrent workers for the organization. Zero means no organization-specific limit.",
    )
    max_vcpus = serializers.IntegerField(
        min_value=0,
        help_text="Maximum active session vCPUs admitted for the organization. Zero means no organization-specific limit.",
    )
    default_worker_cpu = serializers.CharField(
        allow_blank=True,
        help_text="Default worker CPU as a Kubernetes resource quantity, such as 2 or 500m.",
    )
    default_worker_memory = serializers.CharField(
        allow_blank=True,
        help_text="Default worker memory as a Kubernetes resource quantity, such as 8Gi.",
    )
    default_worker_ttl_seconds = serializers.IntegerField(
        min_value=0,
        help_text="Default number of seconds an idle worker remains available for reuse.",
    )
    default_worker_min_hot_idle = serializers.IntegerField(
        min_value=0,
        help_text="Minimum number of idle workers the organization keeps warm.",
    )


class ManagedWarehouseMonitoringTotalsSerializer(serializers.Serializer):
    workers = serializers.IntegerField(min_value=0, help_text="Number of current non-terminal workers.")
    allocated_cpu_cores = serializers.FloatField(
        min_value=0,
        help_text="Total CPU cores allocated to current workers.",
    )
    allocated_memory_bytes = serializers.IntegerField(
        min_value=0,
        help_text="Total memory bytes allocated to current workers.",
    )
    active_sessions = serializers.IntegerField(
        min_value=0,
        help_text="Number of active database sessions across the organization's control planes.",
    )
    running_queries = serializers.IntegerField(
        min_value=0,
        help_text="Number of sessions currently executing a query.",
    )
    queued_connections = serializers.IntegerField(
        min_value=0,
        help_text="Number of connections waiting for worker capacity.",
    )


class ManagedWarehouseMonitoringWorkerSessionSerializer(serializers.Serializer):
    protocol = serializers.CharField(help_text="Connection protocol, such as pg or flight.")
    state = serializers.CharField(help_text="Current database session state.")
    elapsed_ms = serializers.IntegerField(
        min_value=0,
        help_text="Milliseconds elapsed for the current query, or zero when the session is idle.",
    )
    percentage = serializers.FloatField(
        min_value=0,
        allow_null=True,
        help_text="Best-effort query progress percentage, or null when DuckDB cannot estimate progress.",
    )
    rows = serializers.IntegerField(min_value=0, help_text="Rows processed by the current query.")
    total_rows = serializers.IntegerField(
        min_value=0,
        help_text="Estimated total rows for the current query when available.",
    )
    stalled = serializers.BooleanField(help_text="Whether the current query appears stalled.")


class ManagedWarehouseMonitoringWorkerSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Opaque identifier for the worker.")
    state = serializers.CharField(help_text="Current worker lifecycle state.")
    cpu = serializers.CharField(
        allow_blank=True,
        help_text="Worker CPU as a Kubernetes resource quantity, such as 2 or 500m. Blank when unavailable.",
    )
    memory = serializers.CharField(
        allow_blank=True,
        help_text="Worker memory as a Kubernetes resource quantity, such as 8Gi. Blank when unavailable.",
    )
    ttl_seconds = serializers.IntegerField(
        min_value=0,
        help_text="Number of seconds the worker remains available while idle.",
    )
    created_at = serializers.DateTimeField(help_text="UTC timestamp when the worker was created.")
    last_heartbeat_at = serializers.DateTimeField(help_text="UTC timestamp of the worker's latest heartbeat.")
    session = ManagedWarehouseMonitoringWorkerSessionSerializer(
        required=False,
        allow_null=True,
        help_text="Sanitized live session assigned to the worker, when one exists.",
    )


class ManagedWarehouseMonitoringCoverageSerializer(serializers.Serializer):
    cp_responders = serializers.IntegerField(
        min_value=0,
        help_text="Number of control planes that contributed live data.",
    )
    cp_total = serializers.IntegerField(
        min_value=0,
        help_text="Number of control planes queried for live data.",
    )
    partial = serializers.BooleanField(  # type: ignore[assignment]  # Response field shadows DRF's partial option.
        help_text="Whether one or more control planes failed to contribute live data."
    )


class ManagedWarehouseMonitoringSnapshotResponseSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(
        min_value=1,
        max_value=1,
        help_text="Version of the managed warehouse monitoring response schema.",
    )
    org_id = serializers.CharField(help_text="Organization whose managed warehouse is represented.")
    as_of = serializers.DateTimeField(help_text="UTC timestamp when this snapshot was assembled.")
    warehouse = ManagedWarehouseMonitoringWarehouseSerializer(help_text="Managed warehouse lifecycle details.")
    limits = ManagedWarehouseMonitoringLimitsSerializer(help_text="Organization-level worker limits and defaults.")
    totals = ManagedWarehouseMonitoringTotalsSerializer(help_text="Current organization-level activity totals.")
    workers = ManagedWarehouseMonitoringWorkerSerializer(
        many=True,
        help_text="Current non-terminal workers with tenant-safe runtime details.",
    )
    coverage = ManagedWarehouseMonitoringCoverageSerializer(
        help_text="Completeness of the cross-control-plane live data."
    )


class ManagedWarehouseMonitoringSeriesQuerySerializer(serializers.Serializer):
    metric = serializers.ChoiceField(
        choices=MANAGED_WAREHOUSE_MONITORING_METRICS,
        help_text="Allow-listed managed warehouse metric to retrieve.",
    )
    window = serializers.ChoiceField(
        choices=MANAGED_WAREHOUSE_MONITORING_WINDOWS,
        default="24h",
        help_text="Trailing time window to retrieve. Defaults to 24h.",
    )


class ManagedWarehouseMonitoringPointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(help_text="UTC timestamp of the sample.")
    value = serializers.FloatField(help_text="Metric value at the sample timestamp.")


class ManagedWarehouseMonitoringSeriesSerializer(serializers.Serializer):
    labels = serializers.DictField(
        child=serializers.CharField(),
        help_text="Allow-listed labels distinguishing this series, such as query outcome or acquisition source.",
    )
    points = ManagedWarehouseMonitoringPointSerializer(
        many=True,
        help_text="Chronologically ordered metric samples.",
    )


class ManagedWarehouseMonitoringSeriesResponseSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(
        min_value=1,
        max_value=1,
        help_text="Version of the managed warehouse monitoring response schema.",
    )
    org_id = serializers.CharField(help_text="Organization whose managed warehouse is represented.")
    metric = serializers.CharField(help_text="Allow-listed metric returned by this response.")
    unit = serializers.CharField(help_text="Unit for every value in the response.")
    start = serializers.DateTimeField(help_text="Inclusive UTC start of the returned time window.")
    end = serializers.DateTimeField(help_text="Inclusive UTC end of the returned time window.")
    step_seconds = serializers.IntegerField(
        min_value=1,
        help_text="Number of seconds between requested samples.",
    )
    series = ManagedWarehouseMonitoringSeriesSerializer(
        many=True,
        help_text="Metric series grouped by their allow-listed labels.",
    )


def serialize_monitoring_snapshot(raw: object, *, expected_organization_id: str) -> dict[str, object]:
    return _serialize_monitoring_response(
        raw,
        serializer_class=ManagedWarehouseMonitoringSnapshotResponseSerializer,
        expected_organization_id=expected_organization_id,
    )


def serialize_monitoring_series(
    raw: object,
    *,
    expected_organization_id: str,
    expected_metric: str,
) -> dict[str, object]:
    data = _serialize_monitoring_response(
        raw,
        serializer_class=ManagedWarehouseMonitoringSeriesResponseSerializer,
        expected_organization_id=expected_organization_id,
    )
    if data["metric"] != expected_metric:
        raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned a different metric")
    allowed_labels = MANAGED_WAREHOUSE_MONITORING_LABELS[expected_metric]
    for series in cast(list[object], data["series"]):
        if not isinstance(series, Mapping) or not isinstance(series.get("labels"), Mapping):
            raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned invalid series labels")
        if not set(series["labels"]).issubset(allowed_labels):
            raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned unexpected series labels")
    return data


def _serialize_monitoring_response(
    raw: object,
    *,
    serializer_class: type[serializers.Serializer],
    expected_organization_id: str,
) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned an invalid response")

    serializer = serializer_class(data=raw)
    if not serializer.is_valid():
        raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned an invalid response")

    data = dict(serializer.data)
    if str(data["org_id"]) != expected_organization_id:
        raise ManagedWarehouseMonitoringUpstreamError("Monitoring service returned data for a different organization")
    return data

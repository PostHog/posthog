"""Read-only observability helpers that span logs and trace spans (same team)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange, HogQLFilters, ProductKey, TraceSpansQuery

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries, tags_context
from posthog.permissions import PostHogFeatureFlagPermission

from products.tracing.backend.logic import TraceSpansQueryRunner


class _ObservabilityDateRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Start of the range. ISO 8601 or relative (-1h, -24h, -7d). Defaults to -24h when omitted.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text='End of the range. Same format as date_from. Omit or null for "now".',
    )


class ObservabilitySignalSnapshotRequestSerializer(serializers.Serializer):
    dateRange = _ObservabilityDateRangeSerializer(
        required=False,
        help_text="Time window for both logs and span aggregates. Defaults to last 24 hours.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="When set, restrict log and span aggregates to these service_name values.",
    )


class _LogServiceRowSerializer(serializers.Serializer):
    service_name = serializers.CharField()
    count = serializers.IntegerField()


class ObservabilitySignalSnapshotResponseSerializer(serializers.Serializer):
    resolvedDateRange = serializers.DictField(child=serializers.CharField())
    logServiceNames = _LogServiceRowSerializer(many=True)
    traceServiceNames = serializers.ListField(child=serializers.CharField())
    serviceNamesOverlap = serializers.ListField(child=serializers.CharField())
    logOnlyServiceNames = serializers.ListField(child=serializers.CharField())
    traceOnlyServiceNames = serializers.ListField(child=serializers.CharField())
    logsTotal = serializers.IntegerField()
    logsWithJoinableTraceId = serializers.IntegerField()
    joinableTraceIdPercent = serializers.FloatField()
    sampleJoinableTraceIds = serializers.ListField(child=serializers.CharField())


def _joinable_trace_id_predicate_hogql() -> str:
    """HogQL predicate: trace_id is non-empty and not all ASCII zeros (common placeholder)."""
    return "trace_id != '' AND replaceRegexpAll(lower(trace_id), '0', '') != ''"


def _service_filter_suffix(
    placeholders: dict[str, ast.Expr], service_names: list[str] | None
) -> tuple[str, dict[str, ast.Expr]]:
    if not service_names:
        return "", placeholders
    ph = {**placeholders, "svc_tuple": ast.Tuple(exprs=[ast.Constant(value=s) for s in service_names])}
    return " AND service_name IN {svc_tuple}", ph


@extend_schema(tags=["tracing"])
class ObservabilitySignalSnapshotViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    """Aggregates logs + trace_spans joinability and service-name overlap for agents."""

    scope_object = "tracing"
    serializer_class = _FallbackSerializer
    required_scopes = ["tracing:read", "logs:read"]
    posthog_feature_flag = "tracing"
    permission_classes = [PostHogFeatureFlagPermission]

    @extend_schema(
        request=ObservabilitySignalSnapshotRequestSerializer,
        responses={200: OpenApiResponse(response=ObservabilitySignalSnapshotResponseSerializer)},
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        tag_queries(product=ProductKey.TRACING, feature=Feature.QUERY)
        body = request.data or {}
        date_range = self.get_model(body.get("dateRange") or {"date_from": "-24h"}, DateRange)
        service_names: list[str] | None = body.get("serviceNames") or None
        if service_names is not None and len(service_names) == 0:
            service_names = None

        spans_runner = TraceSpansQueryRunner(TraceSpansQuery(dateRange=date_range, limit=1), self.team)
        qdr = spans_runner.query_date_range
        resolved_date_range = {"date_from": qdr.date_from().isoformat(), "date_to": qdr.date_to().isoformat()}
        hogql_filters = HogQLFilters(dateRange=date_range)

        placeholders: dict[str, ast.Expr] = {}
        svc_suffix_logs, ph_logs = _service_filter_suffix(placeholders, service_names)
        svc_suffix_spans, ph_spans = _service_filter_suffix(placeholders, service_names)

        join_pred = _joinable_trace_id_predicate_hogql()

        counts_query = f"""
            SELECT
                count() AS logs_total,
                countIf({join_pred}) AS logs_with_joinable_trace_id
            FROM logs
            WHERE {{filters}}{svc_suffix_logs}
        """

        log_services_query = f"""
            SELECT service_name, count() AS c
            FROM logs
            WHERE {{filters}}{svc_suffix_logs}
            GROUP BY service_name
            ORDER BY c DESC
            LIMIT 100
        """

        trace_services_query = f"""
            SELECT DISTINCT service_name
            FROM posthog.trace_spans
            WHERE {{filters}}{svc_suffix_spans}
            ORDER BY service_name
            LIMIT 200
        """

        samples_query = f"""
            SELECT DISTINCT trace_id
            FROM logs
            WHERE {{filters}} AND {join_pred}{svc_suffix_logs}
            LIMIT 10
        """

        with tags_context(product=ProductKey.LOGS, feature=Feature.QUERY):
            counts_resp = execute_hogql_query(
                counts_query,
                team=self.team,
                filters=hogql_filters,
                placeholders=ph_logs,
                workload=Workload.LOGS,
                query_type="ObservabilitySignalSnapshotCounts",
            )
            log_svc_resp = execute_hogql_query(
                log_services_query,
                team=self.team,
                filters=hogql_filters,
                placeholders=ph_logs,
                workload=Workload.LOGS,
                query_type="ObservabilitySignalSnapshotLogServices",
            )
            samples_resp = execute_hogql_query(
                samples_query,
                team=self.team,
                filters=hogql_filters,
                placeholders=ph_logs,
                workload=Workload.LOGS,
                query_type="ObservabilitySignalSnapshotSamples",
            )

        with tags_context(product=ProductKey.TRACING, feature=Feature.QUERY):
            trace_svc_resp = execute_hogql_query(
                trace_services_query,
                team=self.team,
                filters=hogql_filters,
                placeholders=ph_spans,
                workload=Workload.LOGS,
                query_type="ObservabilitySignalSnapshotTraceServices",
            )

        if counts_resp.error:
            return Response({"error": counts_resp.error}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logs_total = 0
        logs_joinable = 0
        if counts_resp.results:
            logs_total = int(counts_resp.results[0][0] or 0)
            logs_joinable = int(counts_resp.results[0][1] or 0)

        pct = (100.0 * logs_joinable / logs_total) if logs_total else 0.0

        log_service_rows: list[dict[str, int | str]] = []
        if log_svc_resp.results:
            for row in log_svc_resp.results:
                log_service_rows.append({"service_name": str(row[0]), "count": int(row[1] or 0)})

        trace_services: list[str] = []
        if trace_svc_resp.results:
            trace_services = [str(r[0]) for r in trace_svc_resp.results if r and r[0]]

        log_names_ordered = [r["service_name"] for r in log_service_rows]
        log_name_set = set(log_names_ordered)
        trace_set = set(trace_services)
        overlap = sorted(log_name_set & trace_set)
        log_only = sorted(log_name_set - trace_set)
        trace_only = sorted(trace_set - log_name_set)

        sample_ids: list[str] = []
        if samples_resp.results:
            for r in samples_resp.results:
                if r and r[0]:
                    sample_ids.append(str(r[0]))

        payload = {
            "resolvedDateRange": resolved_date_range,
            "logServiceNames": log_service_rows,
            "traceServiceNames": trace_services,
            "serviceNamesOverlap": overlap,
            "logOnlyServiceNames": log_only,
            "traceOnlyServiceNames": trace_only,
            "logsTotal": logs_total,
            "logsWithJoinableTraceId": logs_joinable,
            "joinableTraceIdPercent": round(pct, 4),
            "sampleJoinableTraceIds": sample_ids,
        }
        return Response(payload, status=status.HTTP_200_OK)

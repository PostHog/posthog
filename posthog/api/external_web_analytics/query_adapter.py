from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from rest_framework.utils.urls import remove_query_param, replace_query_param

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    WebOverviewQuery,
    WebOverviewQueryResponse,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
)

from posthog.api.external_web_analytics.serializers import (
    EXTERNAL_WEB_ANALYTICS_NONE_BREAKDOWN_VALUE,
    EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT,
    WebAnalyticsBreakdownRequestSerializer,
    WebAnalyticsOverviewRequestSerializer,
)
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models import Team


@dataclass
class MetricDefinition:
    internal_column: str
    external_key: str
    transformer: Callable[[Any], Any]
    supported_breakdowns: set[WebStatsBreakdown] | None = None  # None = supported for all breakdowns


class BreakdownMetricsConfig:
    def __init__(self):
        self.metrics = {
            "breakdown_value": MetricDefinition(
                internal_column="context.columns.breakdown_value",
                external_key="breakdown_value",
                transformer=self._transform_breakdown_value,
                supported_breakdowns=None,
            ),
            "visitors": MetricDefinition(
                internal_column="context.columns.visitors",
                external_key="visitors",
                transformer=self._transform_count_metric,
                supported_breakdowns=None,
            ),
            "views": MetricDefinition(
                internal_column="context.columns.views",
                external_key="views",
                transformer=self._transform_count_metric,
                supported_breakdowns=None,
            ),
            "bounce_rate": MetricDefinition(
                internal_column="context.columns.bounce_rate",
                external_key="bounce_rate",
                transformer=self._transform_rate_metric,
                supported_breakdowns={WebStatsBreakdown.PAGE, WebStatsBreakdown.INITIAL_PAGE},
            ),
        }

    def get_supported_metrics_for_breakdown(self, breakdown: WebStatsBreakdown) -> dict[str, MetricDefinition]:
        supported = {}
        for key, metric in self.metrics.items():
            if metric.supported_breakdowns is None or breakdown in metric.supported_breakdowns:
                supported[key] = metric
        return supported

    def is_metric_supported(self, metric_key: str, breakdown: WebStatsBreakdown) -> bool:
        if metric_key not in self.metrics:
            return False
        metric = self.metrics[metric_key]
        return metric.supported_breakdowns is None or breakdown in metric.supported_breakdowns

    def _transform_breakdown_value(self, value: Any) -> str:
        current_value = self._extract_current_period_value(value)
        return EXTERNAL_WEB_ANALYTICS_NONE_BREAKDOWN_VALUE if current_value is None else str(current_value)

    def _transform_count_metric(self, value: Any) -> int:
        current_value = self._extract_current_period_value(value)
        return int(current_value) if current_value is not None else 0

    def _transform_rate_metric(self, value: Any) -> float:
        current_value = self._extract_current_period_value(value)
        return float(current_value) if current_value is not None else 0.0

    def _extract_current_period_value(self, value: Any) -> Any:
        return value[0] if isinstance(value, tuple) else value


class ExternalWebAnalyticsQueryAdapter:
    """
    Adapter that uses the internal WebOverviewQueryRunner to provide data for the external API.
    It tries to separate the web analytics query runners from the external API.
    """

    def __init__(self, team: Team, request=None):
        self.team = team
        self.breakdown_metrics_config = BreakdownMetricsConfig()
        self.request = request

    def _get_base_properties(self, host: Optional[str] = None) -> list[EventPropertyFilter]:
        properties = []
        if host:
            properties.append(
                EventPropertyFilter(
                    key="$host",
                    operator=PropertyOperator.EXACT,
                    value=[host],
                )
            )
        return properties

    def _get_datetime_str(self, date_value: date | datetime) -> str:
        return date_value.strftime("%Y-%m-%d")

    def _get_default_modifiers(self) -> HogQLQueryModifiers:
        return HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
            convertToProjectTimezone=True,
        )

    def get_overview_data(self, serializer: WebAnalyticsOverviewRequestSerializer) -> dict[str, Any]:
        data = serializer.validated_data

        query = WebOverviewQuery(
            kind="WebOverviewQuery",
            dateRange=DateRange(
                date_from=self._get_datetime_str(data["date_from"]),
                date_to=self._get_datetime_str(data["date_to"]),
            ),
            properties=self._get_base_properties(data.get("host")),
            filterTestAccounts=data.get("filter_test_accounts", True),
            doPathCleaning=data.get("apply_path_cleaning", True),
            includeRevenue=False,
        )

        runner = WebOverviewQueryRunner(
            query=query,
            team=self.team,
            modifiers=self._get_default_modifiers(),
        )

        response = runner.calculate()

        return self._transform_overview_response(response)

    def get_breakdown_data(self, serializer: WebAnalyticsBreakdownRequestSerializer) -> dict[str, Any]:
        data = serializer.validated_data

        breakdown_by = WebStatsBreakdown(data["breakdown_by"])
        limit = data.get("limit", EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT)
        offset = data.get("offset", 0)

        query = WebStatsTableQuery(
            kind="WebStatsTableQuery",
            breakdownBy=breakdown_by,
            dateRange=DateRange(
                date_from=self._get_datetime_str(data["date_from"]),
                date_to=self._get_datetime_str(data["date_to"]),
            ),
            properties=self._get_base_properties(data.get("host")),
            filterTestAccounts=data.get("filter_test_accounts", True),
            doPathCleaning=data.get("apply_path_cleaning", True),
            includeBounceRate=self.breakdown_metrics_config.is_metric_supported("bounce_rate", breakdown_by),
            limit=limit,
            offset=offset,
        )

        runner = WebStatsTableQueryRunner(
            query=query,
            team=self.team,
            modifiers=self._get_default_modifiers(),
        )

        response = runner.calculate()

        return self._transform_breakdown_response(response, breakdown_by, limit, offset)

    def _transform_breakdown_response(
        self,
        response: WebStatsTableQueryResponse,
        breakdown: WebStatsBreakdown,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """
        Transform the internal WebStatsTableQueryResponse to external API format.

        Internal format:
        - columns: ["context.columns.breakdown_value", "context.columns.visitors", "context.columns.views", ...]
        - results: [["value1", (100, 90), (500, 450)], ...]

        External format:
        {
            "count": total_count,
            "results": [
                {
                    "breakdown_value": "value1",
                    "visitors": 100,
                    "views": 500,
                    ...
                }
            ],
            "next": null,
            "previous": null
        }
        """

        if not response.columns:
            raise ValueError("Query response missing columns - indicates query execution error")

        if not response.results:
            return self._empty_breakdown_response()

        supported_metrics = self.breakdown_metrics_config.get_supported_metrics_for_breakdown(breakdown)
        column_indices = {col: i for i, col in enumerate(response.columns)}

        transformed_results = [
            self._transform_breakdown_row(row, column_indices, supported_metrics) for row in response.results
        ]

        # Generate pagination URLs
        pagination_info = self._get_pagination_info(response, limit, offset)

        return {
            "results": transformed_results,
            "next": pagination_info["next"],
        }

    def _empty_breakdown_response(self) -> dict[str, Any]:
        return {
            "results": [],
            "next": None,
        }

    def _transform_breakdown_row(
        self,
        row: list,
        column_indices: dict[str, int],
        supported_metrics: dict[str, MetricDefinition],
    ) -> dict[str, Any]:
        result = {}

        for metric_def in supported_metrics.values():
            # Check if the internal column exists in the response
            if metric_def.internal_column not in column_indices:
                continue

            col_index = column_indices[metric_def.internal_column]
            raw_value = row[col_index] if col_index < len(row) else None
            result[metric_def.external_key] = metric_def.transformer(raw_value)

        return result

    def _transform_overview_response(self, response: WebOverviewQueryResponse) -> dict[str, Any]:
        """
        Transform the internal WebOverviewQueryResponse to external API format.

        Internal format has results as list of dicts with keys like:
        [
            {"key": "visitors", "value": 1234, ...},
            {"key": "views", "value": 5678, ...},
            ...
        ]

        External format expects:
        {
            "visitors": 1234,
            "views": 5678,
            "sessions": 901,
            "bounce_rate": 0.45,
            "session_duration": 123.4
        }
        """

        metric_mappings = {
            "visitors": ("visitors", lambda v: int(v) if v is not None else 0),
            "views": ("views", lambda v: int(v) if v is not None else 0),
            "sessions": ("sessions", lambda v: int(v) if v is not None else 0),
            "bounce rate": ("bounce_rate", lambda v: (v / 100.0) if v is not None else 0.0),
            "session duration": ("session_duration", lambda v: float(v) if v is not None else 0.0),
        }

        result_dict = {}
        for result in response.results:
            if result.key in metric_mappings:
                external_key, transformer = metric_mappings[result.key]
                result_dict[external_key] = transformer(result.value)

        return {
            "visitors": result_dict.get("visitors", 0),
            "views": result_dict.get("views", 0),
            "sessions": result_dict.get("sessions", 0),
            "bounce_rate": result_dict.get("bounce_rate", 0.0),
            "session_duration": result_dict.get("session_duration", 0.0),
        }

    def _get_pagination_info(
        self, response: WebStatsTableQueryResponse, limit: int, offset: int
    ) -> dict[str, Optional[str]]:
        if not self.request:
            return {"next": None}

        # Use hasMore from the response if available, otherwise check if we have enough results
        has_more = (
            getattr(response, "hasMore", False)
            if hasattr(response, "hasMore")
            else len(response.results or []) >= limit
        )

        next_url = None

        if has_more:
            next_url = self._build_pagination_url(limit, offset + limit)

        return {
            "next": next_url,
        }

    def _build_pagination_url(self, limit: int, offset: int) -> Optional[str]:
        if not self.request:
            return None

        url = self.request.build_absolute_uri()

        url = replace_query_param(url, "limit", limit)

        if offset > 0:
            url = replace_query_param(url, "offset", offset)
        else:
            url = remove_query_param(url, "offset")

        return url

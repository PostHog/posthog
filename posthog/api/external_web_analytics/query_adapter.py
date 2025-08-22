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

        # Add comparison period support for previous period data
        compare_filter = None
        if data.get("compare", False):
            from posthog.schema import CompareFilter

            compare_filter = CompareFilter(compare=True)

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
            compareFilter=compare_filter,
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
        Transform the internal WebOverviewQueryResponse to structured external API format.

        Internal format has results as list of WebOverviewItem objects:
        [
            {"key": "visitors", "kind": "unit", "value": 1234, "previous": 1100, "changeFromPreviousPct": 12.2, ...},
            {"key": "views", "kind": "unit", "value": 5678, "previous": 5200, "changeFromPreviousPct": 9.2, ...},
            ...
        ]

        External format preserves the structured data:
        {
            "visitors": {
                "key": "visitors",
                "kind": "unit",
                "value": 1234,
                "previous": 1100,
                "changeFromPreviousPct": 12.2,
                "isIncreaseBad": false
            },
            "bounce_rate": {
                "key": "bounce_rate",
                "kind": "percentage",
                "value": 0.45,
                "previous": 0.48,
                "changeFromPreviousPct": -6.3,
                "isIncreaseBad": true
            }
        }
        """

        # Map internal keys to external keys for API consistency
        metric_key_mappings = {
            "visitors": "visitors",
            "views": "views",
            "sessions": "sessions",
            "bounce rate": "bounce_rate",
            "session duration": "session_duration",
        }

        result_dict = {}
        for result in response.results:
            if result.key in metric_key_mappings:
                external_key = metric_key_mappings[result.key]

                # Transform values based on metric kind for API consistency
                kind_str = result.kind.value if hasattr(result.kind, "value") else str(result.kind)
                transformed_value = self._transform_metric_value(result.value, kind_str)
                transformed_previous = (
                    self._transform_metric_value(result.previous, kind_str) if result.previous is not None else None
                )

                result_dict[external_key] = {
                    "key": external_key,
                    "kind": kind_str,
                    "value": transformed_value,
                    "previous": transformed_previous,
                    "changeFromPreviousPct": result.changeFromPreviousPct,
                    "isIncreaseBad": result.isIncreaseBad,
                }

        # Ensure all expected metrics are present with defaults
        default_metrics = {
            "visitors": {"key": "visitors", "kind": "unit", "value": 0},
            "views": {"key": "views", "kind": "unit", "value": 0},
            "sessions": {"key": "sessions", "kind": "unit", "value": 0},
            "bounce_rate": {"key": "bounce_rate", "kind": "percentage", "value": 0.0, "isIncreaseBad": True},
            "session_duration": {"key": "session_duration", "kind": "duration_s", "value": 0.0},
        }

        for metric_key, default_data in default_metrics.items():
            if metric_key not in result_dict:
                result_dict[metric_key] = {
                    **default_data,
                    "previous": None,
                    "changeFromPreviousPct": None,
                    "isIncreaseBad": default_data.get("isIncreaseBad"),
                }

        return result_dict

    def _transform_metric_value(self, value: Optional[float], kind: str) -> Optional[float | int]:
        """Transform metric values based on their kind for external API consistency."""
        if value is None:
            # Return appropriate default based on kind
            if kind == "unit":
                return 0
            elif kind == "percentage":
                return 0.0
            else:  # duration_s, currency, etc.
                return 0.0

        if kind == "unit":
            return int(value)
        elif kind == "percentage":
            # Convert percentage to decimal (e.g., 45 -> 0.45) for external API consistency
            return value / 100.0
        else:  # duration_s, currency, etc.
            return float(value)

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

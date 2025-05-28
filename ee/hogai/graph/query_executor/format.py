from datetime import datetime
from math import floor
from typing import Any, Optional, Union, cast

from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.schema import (
    AssistantFunnelsActionsNode,
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    Compare,
    DateRange,
    FunnelStepReference,
    FunnelVizType,
    RetentionPeriod,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    HogQLQuery,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsTopCustomersQuery,
)
from django.conf import settings
from posthog.api.services.query import process_query_dict
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.clickhouse.client.execute_async import get_query_status
from rest_framework.exceptions import APIException
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError
from time import sleep
import json
from django.core.serializers.json import DjangoJSONEncoder


def _format_matrix(matrix: list[list[str]]) -> str:
    lines: list[str] = []
    for row in matrix:
        lines.append("|".join(row))

    return "\n".join(lines).strip()


def _format_number(value: Any) -> str:
    try:
        num = float(value)
        if num.is_integer():
            return str(int(num))
        return f"{num:.5f}".rstrip("0")
    except ValueError:
        return str(value)


def _format_percentage(value: float | int) -> str:
    num = float(value) * 100
    formatted = f"{num:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def _format_duration(
    d: Union[str, int, float, None],
    max_units: Optional[int] = None,
    seconds_precision: Optional[int] = None,
    seconds_fixed: Optional[int] = None,
) -> str:
    """Convert seconds to a human-readable duration string.
    Example: `1d 10hrs 9mins 8s`

    Args:
        d: Duration in seconds
        max_units: Maximum number of units to display
        seconds_precision: Precision for seconds (significant figures)
        seconds_fixed: Fixed decimal places for seconds

    Returns:
        Human readable duration string
    """
    if not d or max_units == 0:
        return ""

    try:
        d = float(d)
    except (ValueError, TypeError):
        return ""

    if d < 0:
        return f"-{_format_duration(-d, max_units, seconds_precision, seconds_fixed)}"

    if d == 0:
        return "0s"

    if d < 1:
        return f"{round(d * 1000)}ms"

    if d < 60:
        if seconds_precision is not None:
            # Round to significant figures and strip trailing .0
            return f"{float(f'%.{seconds_precision}g' % d):.0f}s".replace(".0s", "s")
        # Round to fixed decimal places and strip trailing .0
        fixed = seconds_fixed if seconds_fixed is not None else 0
        return f"{float(f'%.{fixed}f' % d):.0f}s".replace(".0s", "s")

    days = floor(d / 86400)
    h = floor((d % 86400) / 3600)
    m = floor((d % 3600) / 60)
    s = round((d % 3600) % 60)

    day_display = f"{days}d" if days > 0 else ""
    h_display = f"{h}h" if h > 0 else ""
    m_display = f"{m}m" if m > 0 else ""
    s_display = f"{s}s" if s > 0 else ("0s" if not (h_display or m_display) else "")

    if days > 0:
        units = [u for u in [day_display, h_display] if u]
    else:
        units = [u for u in [h_display, m_display, s_display] if u]

    if max_units is not None:
        units = units[:max_units]

    return " ".join(units)


def _strip_datetime_seconds(date: str) -> str:
    return datetime.fromisoformat(date).strftime("%Y-%m-%d %H:%M" if ":" in date else "%Y-%m-%d")


def _replace_breakdown_labels(name: str) -> str:
    return name.replace(BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_OTHER_DISPLAY).replace(
        BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_NULL_DISPLAY
    )


class TrendsResultsFormatter:
    """
    Compresses and formats trends results into a LLM-friendly string.

    Single/Multiple series:
    ```
    Date|Series Label 1|Series Label 2
    Date 1|value1|value2
    Date 2|value1|value2
    ```
    """

    def __init__(self, query: AssistantTrendsQuery, results: list[dict[str, Any]]):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        if len(results) == 0:
            return "No data recorded for this time period."

        current = []
        previous = []

        for result in results:
            if result.get("compare_label") == Compare.CURRENT:
                current.append(result)
            elif result.get("compare_label") == Compare.PREVIOUS:
                previous.append(result)

        # If there isn't data in comparison, the series will be omitted.
        if len(previous) > 0 and len(current) > 0:
            template = f"Previous period:\n{self._format_results(previous)}\n\nCurrent period:\n{self._format_results(current)}"
            return template

        return self._format_results(results)

    def _format_aggregated_values(self, results: list[dict[str, Any]]) -> str:
        # Get dates and series labels
        result = results[0]
        dates = result.get("action", {}).get("days") or []
        if len(dates) == 0:
            range = "All time"
        else:
            range = f"{dates[0]} to {dates[-1]}"

        series_labels = []
        for series in results:
            label = f"Aggregated value for {self._extract_series_label(series)}"
            series_labels.append(label)

        # Build header row
        matrix: list[list[str]] = []
        header = ["Date range", *series_labels]
        matrix.append(header)

        row = [range]
        for series in results:
            row.append(_format_number(series["aggregated_value"]))
        matrix.append(row)

        return _format_matrix(matrix)

    def _format_non_aggregated_values(self, results: list[dict[str, Any]]) -> str:
        # Get dates and series labels
        result = results[0]
        dates = result["days"]

        series_labels = []
        for series in results:
            label = self._extract_series_label(series)

            series_labels.append(label)

        # Build header row
        matrix: list[list[str]] = []
        header = ["Date", *series_labels]
        matrix.append(header)

        # Build data rows
        for i, date in enumerate(dates):
            row = [_strip_datetime_seconds(date)]
            for series in results:
                row.append(_format_number(series["data"][i]))
            matrix.append(row)

        return _format_matrix(matrix)

    def _extract_series_label(self, series: dict[str, Any]) -> str:
        action = series.get("action")
        name = series["label"]
        if isinstance(action, dict):
            custom_name = action.get("custom_name")
            if custom_name is not None:
                name = custom_name
        if series.get("breakdown_value") is not None:
            if isinstance(series["breakdown_value"], list):
                breakdown_label = ", ".join(str(v) for v in series["breakdown_value"])
            else:
                breakdown_label = str(series["breakdown_value"])
            name += f" breakdown for the value `{breakdown_label}`"

        return _replace_breakdown_labels(name)

    def _format_results(self, results: list[dict]) -> str:
        # Get dates and series labels
        result = results[0]
        aggregation_applied = result.get("aggregated_value") is not None
        if aggregation_applied:
            return self._format_aggregated_values(results)
        else:
            return self._format_non_aggregated_values(results)


class RetentionResultsFormatter:
    """
    Compresses and formats retention results into a LLM-friendly string.

    Example answer:
    ```
    Start Date: date
    Period: period
    Date|Number of persons on date|Day 0|Day 1|Day 2|Day 3
    2024-01-28|Total Persons on Date 1|Percentage of retained users on 2024-01-29|Percentage of retained users on 2024-01-30|Percentage of retained users on 2024-01-31
    2024-01-29|Total Persons on Date 2|Percentage of retained users on 2024-01-30|Percentage of retained users on 2024-01-31
    2024-01-30|Total Persons on Date 3|Percentage of retained users on 2024-01-31
    2024-01-31|Total Persons on Date 4
    ```
    """

    def __init__(self, query: AssistantRetentionQuery, results: list[dict]):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        period = self._period

        if not results:
            return "No data recorded for this time period."

        matrix = [["Date", "Number of persons on date"]]
        for series in results:
            matrix[0].append(series["label"])
            row = [_strip_datetime_seconds(series["date"])]
            for idx, val in enumerate(series["values"]):
                initial_count = series["values"][0]["count"]
                count = val["count"]
                if idx == 0:
                    row.append(_format_number(count))
                    row.append("100%")
                elif initial_count != 0:
                    row.append(_format_percentage(count / initial_count))
                else:
                    row.append("0%")
            matrix.append(row)

        date_from = _strip_datetime_seconds(results[0]["date"])
        date_to = _strip_datetime_seconds(results[-1]["date"])
        return f"Date range: {date_from} to {date_to}\nTime interval: {period}\n{_format_matrix(matrix)}"

    @property
    def _period(self) -> RetentionPeriod:
        return self._query.retentionFilter.period or RetentionPeriod.DAY


class FunnelResultsFormatter:
    """
    Compresses and formats funnels results into a LLM-friendly string.

    Example answer for a steps funnel:
    ```
    Date range
    Metric|Label 1|Label 2
    Total person count|value1|value2
    Conversion rate|value1|value2
    Drop-off rate|value1|value2
    Average conversion time|value1|value2
    Median conversion time|value1|value2
    ```

    Example answer for a time to convert funnel:
    ```
    Date range: 2025-01-20 00:00:00 to 2025-01-22 23:59:59

    Events: $pageview (custom) -> $ai_trace
    Time|User distribution
    10m|100%
    10m 1s|0%

    The user distribution is the percentage of users who completed the funnel in the given period.
    ```

    Example answer for funnel trends:
    ```
    Date|$pageview (custom) -> $ai_trace conversion|$pageview (custom) -> $ai_trace drop-off
    2025-01-05|10%|90%
    2025-01-12|91%|9%
    2025-01-19|100%|0%
    2025-01-26|100%|0%
    ```
    """

    def __init__(
        self,
        query: AssistantFunnelsQuery,
        results: list[dict[str, Any]] | list[list[dict[str, Any]]] | dict[str, Any],
        team: Team,
        utc_now_datetime: datetime,
    ):
        self._query = query
        self._results = results
        date_range = DateRange.model_validate(query.dateRange.model_dump()) if query.dateRange else None
        self._query_date_range = QueryDateRange(date_range, team, query.interval, utc_now_datetime)

    def format(self) -> str:
        if self._viz_type == FunnelVizType.STEPS:
            return self._format_steps()
        elif self._viz_type == FunnelVizType.TIME_TO_CONVERT:
            return self._format_time_to_convert()
        else:
            return self._format_trends()

    def _format_steps(self) -> str:
        results = self._results
        if len(results) == 0 or not isinstance(results, list):
            return "No data recorded for this time period."

        results = cast(list[dict[str, Any]] | list[list[dict[str, Any]]], results)

        matrixes = []
        if isinstance(results[0], list):
            for result in results:
                matrixes.append(self._format_steps_series(cast(list[dict], result)))
        else:
            matrixes.append(self._format_steps_series(cast(list[dict], results)))

        conversion_type_hint = 'Conversion and drop-off rates are calculated in overall. For example, "Conversion rate: 9%" means that 9% of users from the first step completed the funnel.'
        if self._step_reference == FunnelStepReference.PREVIOUS:
            conversion_type_hint = "Conversion and drop-off rates are relative to the previous steps. For example, 'Conversion rate: 90%' means that 90% of users from the previous step completed the funnel."

        joined_matrixes = "\n\n".join(matrixes)
        return f"{self._format_time_range()}\n\n{joined_matrixes}\n\n{conversion_type_hint}"

    def _format_time_to_convert(self) -> str:
        results = self._results
        if len(results) == 0 or not isinstance(results, dict):
            return "No data recorded for this time period."

        matrix: list[list[Any]] = [
            ["Average time to convert", "User distribution"],
        ]
        for series in results.get("bins") or []:
            matrix.append([_format_duration(series[0]), _format_percentage(series[1])])

        hint = "The user distribution is the percentage of users who completed the funnel in the given period."
        return f"{self._format_time_range()}\n\nEvents: {self._format_filter_series_label()}\n{_format_matrix(matrix)}\n\n{hint}"

    def _format_trends(self) -> str:
        results = self._results
        if len(results) == 0 or not isinstance(results, list):
            return "No data recorded for this time period."

        results = cast(list[dict[str, Any]], results)
        return self._format_trends_series(results)

    @property
    def _step_reference(self) -> FunnelStepReference:
        step_reference = FunnelStepReference.TOTAL
        if self._query.funnelsFilter and self._query.funnelsFilter.funnelStepReference:
            step_reference = self._query.funnelsFilter.funnelStepReference
        return step_reference

    @property
    def _viz_type(self) -> FunnelVizType:
        viz_type = FunnelVizType.STEPS
        if self._query.funnelsFilter and self._query.funnelsFilter.funnelVizType:
            viz_type = self._query.funnelsFilter.funnelVizType
        return viz_type

    def _format_steps_series(self, results: list[dict[str, Any]]) -> str:
        matrix: list[list[Any]] = [
            ["Metric"],
            ["Total person count"],
            ["Conversion rate"],
            ["Dropoff rate"],
            ["Average conversion time"],
            ["Median conversion time"],
        ]

        for idx, series in enumerate(results):
            label = series["name"]
            if series.get("custom_name") is not None:
                label = f"{label} {series['custom_name']}"

            matrix[0].append(label)
            matrix[1].append(series["count"])

            this_step_count = series["count"]
            first_step_count = matrix[1][1]
            if idx == 0:
                conversion_rate = "100%"
                dropoff_rate = "0%"
            elif self._step_reference == FunnelStepReference.PREVIOUS:
                prev_count = matrix[1][idx]
                if prev_count != 0:
                    conversion_rate = _format_percentage(this_step_count / prev_count)
                    dropoff_rate = _format_percentage((prev_count - this_step_count) / prev_count)
                else:
                    conversion_rate = "0%"
                    dropoff_rate = "100%"
            else:
                if first_step_count != 0:
                    conversion_rate = _format_percentage(this_step_count / first_step_count)
                    dropoff_rate = _format_percentage((first_step_count - this_step_count) / first_step_count)
                else:
                    conversion_rate = "0%"
                    dropoff_rate = "100%"

            matrix[2].append(conversion_rate)
            matrix[3].append(dropoff_rate)

            matrix[4].append(
                _format_duration(series["average_conversion_time"])
                if series["average_conversion_time"] is not None
                else "-"
            )
            matrix[5].append(
                _format_duration(series["median_conversion_time"])
                if series["median_conversion_time"] is not None
                else "-"
            )

        matrix[1] = [_format_number(cell) for cell in matrix[1]]

        formatted_matrix = _format_matrix(matrix)
        if results[0].get("breakdown_value") is not None:
            breakdown_value = results[0]["breakdown_value"]
            if isinstance(breakdown_value, list):
                breakdown_value = ", ".join(breakdown_value)
            return f"---{breakdown_value}\n{formatted_matrix}"
        return formatted_matrix

    def _format_time_range(self) -> str:
        return f"Date range: {self._query_date_range.date_from_str} to {self._query_date_range.date_to_str}"

    def _format_filter_series_label(self) -> str:
        series_labels: list[str] = []
        for node in self._query.series:
            if isinstance(node, AssistantFunnelsEventsNode) and node.custom_name is not None:
                series_labels.append(f"{node.event} ({node.custom_name})")
            elif isinstance(node, AssistantFunnelsActionsNode):
                series_labels.append(f"{node.name} (action {node.id})")
            else:
                series_labels.append(node.event)
        return " -> ".join(series_labels)

    def _format_trends_series(self, results: list[dict[str, Any]]) -> str:
        # Get dates and series labels
        result = results[0]
        dates = result["days"]
        label = self._format_filter_series_label()

        # Build header row
        header = ["Date"]
        for series in results:
            label_with_breakdown = label
            if series.get("breakdown_value") is not None:
                breakdown = ", ".join([str(value) for value in series["breakdown_value"]])
                label_with_breakdown = f"{label} {breakdown} breakdown"
            header.append(f"{label_with_breakdown} conversion")
            header.append(f"{label_with_breakdown} drop-off")

        matrix: list[list[str]] = [
            header,
        ]

        # Build data rows
        for i, date in enumerate(dates):
            row = [_strip_datetime_seconds(date)]
            for series in results:
                row.append(_format_percentage(series["data"][i] / 100))
                row.append(_format_percentage((100 - series["data"][i]) / 100))
            matrix.append(row)

        return _format_matrix(matrix)


class SQLResultsFormatter:
    """
    Compresses and formats SQL results into a LLM-friendly string.
    """

    def __init__(self, query: AssistantHogQLQuery, results: list[dict[str, Any]], columns: list[str]):
        self._query = query
        self._results = results
        self._columns = columns

    def format(self) -> str:
        lines: list[str] = []
        lines.append("|".join(self._columns))
        for row in self._results:
            lines.append("|".join([str(cell) for cell in row.values()]))
        return "\n".join(lines)


class RevenueAnalyticsOverviewResultsFormatter:
    """
    Compresses and formats revenue analytics overview results into a LLM-friendly string.

    Example answer:
    ```
    Revenue: $12,345.67
    Paying Customer Count: 123
    Average Revenue Per Customer: $100.37
    ```
    """

    def __init__(self, query: RevenueAnalyticsOverviewQuery, results: list[dict[str, Any]]):
        self._query = query
        self._results = results

    def format(self) -> str:
        if not self._results:
            return "No revenue data available for this time period."

        lines: list[str] = []
        for item in self._results:
            key = item.get("key", "")
            value = item.get("value", 0)

            if key == "revenue":
                lines.append(f"Revenue: ${_format_number(value)}")
            elif key == "paying_customer_count":
                lines.append(f"Paying Customer Count: {_format_number(value)}")
            elif key == "avg_revenue_per_customer":
                lines.append(f"Average Revenue Per Customer: ${_format_number(value)}")
            else:
                # Fallback for any other keys
                formatted_key = key.replace("_", " ").title()
                lines.append(f"{formatted_key}: {_format_number(value)}")

        return "\n".join(lines)


class RevenueAnalyticsGrowthRateResultsFormatter:
    """
    Compresses and formats revenue analytics growth rate results into a LLM-friendly string.

    Example answer:
    ```
    Month|MRR|Previous MRR|Growth Rate
    2024-01|$1,000|$900|11.11%
    2024-02|$1,100|$1,000|10.00%
    ```
    """

    def __init__(self, query: RevenueAnalyticsGrowthRateQuery, results: list[list[Any]]):
        self._query = query
        self._results = results

    def format(self) -> str:
        if not self._results:
            return "No growth rate data available for this time period."

        matrix: list[list[str]] = [["Month", "MRR", "Previous MRR", "Growth Rate"]]

        for row in self._results:
            if len(row) >= 4:
                month = str(row[0])
                mrr = f"${_format_number(row[1])}"
                prev_mrr = f"${_format_number(row[2])}" if row[2] is not None else "N/A"
                growth_rate = _format_percentage(row[3]) if row[3] is not None else "N/A"
                matrix.append([month, mrr, prev_mrr, growth_rate])

        return _format_matrix(matrix)


class RevenueAnalyticsTopCustomersResultsFormatter:
    """
    Compresses and formats revenue analytics top customers results into a LLM-friendly string.

    Example answer:
    ```
    Customer|Customer ID|Revenue|Month
    Customer A|123|$1,000|2024-01
    Customer B|456|$800|2024-01
    ```
    """

    def __init__(self, query: RevenueAnalyticsTopCustomersQuery, results: list[list[Any]]):
        self._query = query
        self._results = results

    def format(self) -> str:
        if not self._results:
            return "No top customers data available for this time period."

        matrix: list[list[str]] = [["Customer", "Customer ID", "Revenue", "Month"]]

        for row in self._results:
            if len(row) >= 4:
                customer_name = str(row[0]) if row[0] is not None else "Unknown"
                customer_id = str(row[1]) if row[1] is not None else "N/A"
                revenue = f"${_format_number(row[2])}" if row[2] is not None else "$0"
                month = str(row[3]) if row[3] is not None else "N/A"
                matrix.append([customer_name, customer_id, revenue, month])

        return _format_matrix(matrix)


class QueryRunner:
    """
    Reusable class for executing queries and formatting results.
    Can be used by QueryExecutorNode and other components that need to run and format queries.
    """

    def __init__(self, team, utc_now_datetime):
        self._team = team
        self._utc_now_datetime = utc_now_datetime

    def run_and_format_query(self, query, execution_mode=None) -> str:
        """
        Run a query and format the results as a string.

        Args:
            query: The query object (AssistantTrendsQuery, AssistantFunnelsQuery, etc.)
            execution_mode: Optional execution mode override

        Returns:
            Formatted results as a string
        """
        results, _ = self.run_and_format_query_with_fallback_info(query, execution_mode)
        return results

    def run_and_format_query_with_fallback_info(self, query, execution_mode=None) -> tuple[str, bool]:
        """
        Run a query and format the results as a string, with fallback information.

        Args:
            query: The query object (AssistantTrendsQuery, AssistantFunnelsQuery, etc.)
            execution_mode: Optional execution mode override

        Returns:
            Tuple of (formatted results as string, whether fallback was used)
        """
        if execution_mode is None:
            execution_mode = (
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
                if not settings.TEST
                else ExecutionMode.CALCULATE_BLOCKING_ALWAYS
            )

        try:
            results_response = process_query_dict(
                self._team,
                query.model_dump(mode="json"),
                execution_mode=execution_mode,
            )

            # Handle the response properly - process_query_dict returns a dict, not a model
            if isinstance(results_response, dict):
                response_dict = results_response
            else:
                response_dict = results_response.model_dump(mode="json")

            # If response has an async query_status, that's always the thing to use
            if query_status := response_dict.get("query_status"):
                if not query_status["complete"]:
                    # If it's an in-progress (likely just kicked off) status, let's poll until complete
                    for wait_ms in range(100, 12000, 100):  # 726 s in total, if my math is correct
                        sleep(wait_ms / 1000)
                        query_status = get_query_status(team_id=self._team.pk, query_id=query_status["id"]).model_dump(
                            mode="json"
                        )
                        if query_status["complete"]:
                            break
                    else:
                        raise APIException(
                            "Query hasn't completed in time. It's worth trying again, maybe with a shorter time range."
                        )
                # With results ready, let's first check for errors - then actually use the results
                if query_status.get("error"):
                    if error_message := query_status.get("error_message"):
                        raise APIException(error_message)
                    raise Exception("Query failed")
                response_dict = query_status["results"]

        except (APIException, ExposedHogQLError, ExposedCHQueryError) as err:
            err_message = str(err)
            if isinstance(err, APIException):
                if isinstance(err.detail, dict):
                    err_message = ", ".join(f"{key}: {value}" for key, value in err.detail.items())
                elif isinstance(err.detail, list):
                    err_message = ", ".join(map(str, err.detail))
            raise Exception(f"There was an error running this query: {err_message}")
        except Exception:
            raise Exception("There was an unknown error running this query.")

        try:
            formatted_results = self._compress_results(query, response_dict)
            return formatted_results, False  # No fallback used
        except Exception as err:
            if isinstance(err, NotImplementedError):
                raise
            # In case something is wrong with the compression, we fall back to the plain JSON.
            fallback_results = json.dumps(response_dict["results"], cls=DjangoJSONEncoder, separators=(",", ":"))
            return fallback_results, True  # Fallback was used

    def _compress_results(self, query, response: dict) -> str:
        """Format query results based on query type."""
        # Handle assistant-specific queries directly
        if isinstance(query, AssistantTrendsQuery):
            return TrendsResultsFormatter(query, response["results"]).format()
        elif isinstance(query, AssistantFunnelsQuery):
            return FunnelResultsFormatter(query, response["results"], self._team, self._utc_now_datetime).format()
        elif isinstance(query, AssistantRetentionQuery):
            return RetentionResultsFormatter(query, response["results"]).format()
        elif isinstance(query, AssistantHogQLQuery):
            return SQLResultsFormatter(query, response["results"], response["columns"]).format()

        # Handle full UI queries by casting to assistant query types
        # Handle revenue analytics queries
        elif isinstance(query, RevenueAnalyticsOverviewQuery):
            return RevenueAnalyticsOverviewResultsFormatter(query, response["results"]).format()
        elif isinstance(query, RevenueAnalyticsGrowthRateQuery):
            return RevenueAnalyticsGrowthRateResultsFormatter(query, response["results"]).format()
        elif isinstance(query, RevenueAnalyticsTopCustomersQuery):
            return RevenueAnalyticsTopCustomersResultsFormatter(query, response["results"]).format()

        elif isinstance(query, TrendsQuery):
            # Cast to AssistantTrendsQuery for formatting
            assistant_query = cast(AssistantTrendsQuery, query)
            return TrendsResultsFormatter(assistant_query, response["results"]).format()
        elif isinstance(query, FunnelsQuery):
            # Cast to AssistantFunnelsQuery for formatting
            assistant_query = cast(AssistantFunnelsQuery, query)
            return FunnelResultsFormatter(
                assistant_query, response["results"], self._team, self._utc_now_datetime
            ).format()
        elif isinstance(query, RetentionQuery):
            # Cast to AssistantRetentionQuery for formatting
            assistant_query = cast(AssistantRetentionQuery, query)
            return RetentionResultsFormatter(assistant_query, response["results"]).format()
        elif isinstance(query, HogQLQuery):
            # Cast to AssistantHogQLQuery for formatting
            assistant_query = cast(AssistantHogQLQuery, query)
            return SQLResultsFormatter(assistant_query, response["results"], response["columns"]).format()

        raise NotImplementedError(f"Unsupported query type: {type(query)}")

from datetime import datetime
from typing import Any, cast

from posthog.schema import (
    ActionsNode,
    AssistantFunnelsActionsNode,
    AssistantFunnelsEventsNode,
    AssistantFunnelsQuery,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    FunnelsQuery,
    FunnelStepReference,
    FunnelVizType,
)

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team

from .utils import format_duration, format_matrix, format_number, format_percentage, strip_datetime_seconds


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
        query: AssistantFunnelsQuery | FunnelsQuery,
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
            matrix.append([format_duration(series[0]), format_percentage(series[1])])

        hint = "The user distribution is the percentage of users who completed the funnel in the given period."
        return f"{self._format_time_range()}\n\nEvents: {self._format_filter_series_label()}\n{format_matrix(matrix)}\n\n{hint}"

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
                    conversion_rate = format_percentage(this_step_count / prev_count)
                    dropoff_rate = format_percentage((prev_count - this_step_count) / prev_count)
                else:
                    conversion_rate = "0%"
                    dropoff_rate = "100%"
            else:
                if first_step_count != 0:
                    conversion_rate = format_percentage(this_step_count / first_step_count)
                    dropoff_rate = format_percentage((first_step_count - this_step_count) / first_step_count)
                else:
                    conversion_rate = "0%"
                    dropoff_rate = "100%"

            matrix[2].append(conversion_rate)
            matrix[3].append(dropoff_rate)

            matrix[4].append(
                format_duration(series["average_conversion_time"])
                if series["average_conversion_time"] is not None
                else "-"
            )
            matrix[5].append(
                format_duration(series["median_conversion_time"])
                if series["median_conversion_time"] is not None
                else "-"
            )

        matrix[1] = [format_number(cell) for cell in matrix[1]]

        formatted_matrix = format_matrix(matrix)
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
            if isinstance(node, AssistantFunnelsEventsNode | EventsNode):
                if node.custom_name is not None:
                    series_labels.append(f"{node.event} ({node.custom_name})")
                else:
                    series_labels.append(f"{node.event}")
            elif isinstance(node, AssistantFunnelsActionsNode | ActionsNode):
                series_labels.append(f"{node.name} (action {node.id})")
            elif isinstance(node, DataWarehouseNode):
                if node.custom_name is not None:
                    series_labels.append(f"{node.name} ({node.custom_name})")
                else:
                    series_labels.append(f"{node.name}")
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
            row = [strip_datetime_seconds(date)]
            for series in results:
                row.append(format_percentage(series["data"][i] / 100))
                row.append(format_percentage((100 - series["data"][i]) / 100))
            matrix.append(row)

        return format_matrix(matrix)

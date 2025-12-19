from typing import Any

from posthog.schema import AssistantTrendsQuery, Compare, TrendsQuery

from .utils import format_matrix, format_number, replace_breakdown_labels, strip_datetime_seconds


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

    def __init__(
        self,
        query: AssistantTrendsQuery | TrendsQuery,
        results: list[dict[str, Any]],
    ):
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
            row.append(format_number(series["aggregated_value"]))
        matrix.append(row)

        return format_matrix(matrix)

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
            row = [strip_datetime_seconds(date)]
            for series in results:
                row.append(format_number(series["data"][i]))
            matrix.append(row)

        return format_matrix(matrix)

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

        return replace_breakdown_labels(name)

    def _format_results(self, results: list[dict]) -> str:
        # Get dates and series labels
        result = results[0]
        aggregation_applied = result.get("aggregated_value") is not None
        if aggregation_applied:
            return self._format_aggregated_values(results)
        else:
            return self._format_non_aggregated_values(results)

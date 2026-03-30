from collections import defaultdict
from typing import Any

from posthog.schema import AssistantLifecycleQuery, LifecycleQuery

from .utils import format_matrix, format_number, strip_datetime_seconds

STATUS_ORDER = ["new", "returning", "resurrecting", "dormant"]
STATUS_LABELS = ["New", "Returning", "Resurrecting", "Dormant"]


class LifecycleResultsFormatter:
    """
    Compresses and formats lifecycle results into a LLM-friendly string.

    Single series:
    ```
    Date|New|Returning|Resurrecting|Dormant
    2025-10-01|6936|29541|13263|-16735
    2025-11-01|7101|30794|12662|-18946
    ```

    Multiple series:
    ```
    Event: $pageview
    Date|New|Returning|Resurrecting|Dormant
    2025-10-01|6936|29541|13263|-16735

    Event: sign up
    Date|New|Returning|Resurrecting|Dormant
    2025-10-01|100|200|50|-80
    ```
    """

    def __init__(
        self,
        query: AssistantLifecycleQuery | LifecycleQuery,
        results: list[dict[str, Any]],
    ):
        self._query = query
        self._results = results

    def format(self) -> str:
        if not self._results:
            return "No data recorded for this time period."

        # Group results by event series (using action order as key)
        series_groups: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        for result in self._results:
            order = result.get("action", {}).get("order", 0)
            status = result.get("status", "")
            series_groups[order][status] = result

        sections: list[str] = []
        multi_series = len(series_groups) > 1

        for order in sorted(series_groups.keys()):
            statuses = series_groups[order]
            section = self._format_series(statuses, multi_series)
            if section:
                sections.append(section)

        return "\n\n".join(sections)

    def _format_series(self, statuses: dict[str, dict[str, Any]], multi_series: bool) -> str:
        # Get dates from any available status
        any_result = next(iter(statuses.values()))
        days = any_result.get("days", [])
        if not days:
            return ""

        series_name = self._extract_series_name(any_result)

        matrix: list[list[str]] = []
        header = ["Date", *STATUS_LABELS]
        matrix.append(header)

        for i, day in enumerate(days):
            row = [strip_datetime_seconds(day)]
            for status in STATUS_ORDER:
                status_result = statuses.get(status)
                if status_result and i < len(status_result.get("data", [])):
                    row.append(format_number(status_result["data"][i]))
                else:
                    row.append("0")
            matrix.append(row)

        formatted = format_matrix(matrix)
        if multi_series:
            return f"Event: {series_name}\n{formatted}"
        return formatted

    @staticmethod
    def _extract_series_name(result: dict[str, Any]) -> str:
        action = result.get("action")
        if isinstance(action, dict):
            custom_name = action.get("custom_name")
            if custom_name:
                return custom_name
            name = action.get("name")
            if name:
                return name
        # Fallback: strip status suffix from label
        label = result.get("label", "")
        for status in STATUS_ORDER:
            suffix = f" - {status}"
            if label.endswith(suffix):
                return label[: -len(suffix)]
        return label

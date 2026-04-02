from typing import Any

import structlog

from .utils import format_matrix, format_number, strip_datetime_seconds

logger = structlog.get_logger(__name__)

STATUS_ORDER = ["new", "returning", "resurrecting", "dormant"]


class LifecycleResultsFormatter:
    """
    Compresses and formats lifecycle results into a LLM-friendly string.

    ```
    Date|new|returning|resurrecting|dormant
    2025-01-20|46|120|15|-30
    2025-01-21|38|105|22|-45
    ```
    """

    def __init__(
        self,
        results: list[dict[str, Any]],
    ):
        self._results = results

    def format(self) -> str:
        if not self._results:
            return "No data recorded for this time period."

        by_status: dict[str, dict[str, Any]] = {}
        for result in self._results:
            status = result.get("status")
            if status:
                if status in by_status:
                    logger.warning("lifecycle_duplicate_status", status=status)
                by_status[status] = result

        if not by_status:
            return "No data recorded for this time period."

        first = next(iter(by_status.values()))
        days = first.get("days", [])
        if not days:
            return "No data recorded for this time period."

        statuses = [s for s in STATUS_ORDER if s in by_status]

        matrix: list[list[str]] = []
        matrix.append(["Date", *statuses])

        for i, day in enumerate(days):
            row = [strip_datetime_seconds(day)]
            for status in statuses:
                series = by_status[status]
                data = series.get("data", [])
                value = data[i] if i < len(data) else 0
                row.append(format_number(value))
            matrix.append(row)

        return format_matrix(matrix)

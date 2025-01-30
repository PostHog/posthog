from typing import Any

from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.schema import Compare


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


def _extract_series_label(series: dict) -> str:
    action = series.get("action")
    name = series["label"]
    if isinstance(action, dict):
        custom_name = action.get("custom_name")
        if custom_name is not None:
            name = custom_name
    if series.get("breakdown_value") is not None:
        name += " (breakdown)"

    # Replace breakdown labels
    name.replace(BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_OTHER_DISPLAY)
    name.replace(BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_NULL_DISPLAY)

    return name


def _format_trends_results(results: list[dict]) -> str:
    # Get dates and series labels
    result = results[0]
    dates = result["days"]
    series_labels = []
    for series in results:
        label = _extract_series_label(series)

        series_labels.append(label)

    # Build header row
    matrix: list[list[str]] = []
    header = ["Date", *series_labels]
    matrix.append(header)

    # Build data rows
    for i, date in enumerate(dates):
        row = [date]
        for result in results:
            row.append(_format_number(result["data"][i]))
        matrix.append(row)

    return _format_matrix(matrix)


def compress_and_format_trends_results(results: list[dict]) -> str:
    """
    Compresses and formats trends results into a LLM-friendly string.

    Single/Multiple series:
    ```
    Date|Series Label 1|Series Label 2
    Date 1|value1|value2
    Date 2|value1|value2
    ```
    """
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
        template = f"Previous period:\n{_format_trends_results(previous)}\n\nCurrent period:\n{_format_trends_results(current)}"
        return template

    return _format_trends_results(results)


def compress_and_format_funnels_results(results: list[dict]) -> str:
    pass


def compress_and_format_retention_results(results: list[dict]) -> str:
    pass

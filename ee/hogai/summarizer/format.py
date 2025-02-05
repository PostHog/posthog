from datetime import datetime
from math import floor
from typing import Any, Optional, Union, cast

from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from posthog.schema import Compare, FunnelStepReference, RetentionPeriod


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


def _extract_series_label(series: dict) -> str:
    action = series.get("action")
    name = series["label"]
    if isinstance(action, dict):
        custom_name = action.get("custom_name")
        if custom_name is not None:
            name = custom_name
    if series.get("breakdown_value") is not None:
        name += " (breakdown)"

    return _replace_breakdown_labels(name)


def _format_trends_aggregated_values(results: list[dict]) -> str:
    # Get dates and series labels
    result = results[0]
    dates = result.get("action", {}).get("days") or []
    if len(dates) == 0:
        range = "All time"
    else:
        range = f"{dates[0]} to {dates[-1]}"

    series_labels = []
    for series in results:
        label = f"Aggregated value for {_extract_series_label(series)}"
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


def _format_trends_non_aggregated_values(results: list[dict]) -> str:
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
        row = [_strip_datetime_seconds(date)]
        for series in results:
            row.append(_format_number(series["data"][i]))
        matrix.append(row)

    return _format_matrix(matrix)


def _format_trends_results(results: list[dict]) -> str:
    # Get dates and series labels
    result = results[0]
    aggregation_applied = result.get("aggregated_value") is not None
    if aggregation_applied:
        return _format_trends_aggregated_values(results)
    else:
        return _format_trends_non_aggregated_values(results)


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


def _format_funnels_results(results: list[dict], conversion_type: FunnelStepReference) -> str:
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
        elif conversion_type == FunnelStepReference.PREVIOUS:
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
            _format_duration(series["median_conversion_time"]) if series["median_conversion_time"] is not None else "-"
        )

    matrix[1] = [_format_number(cell) for cell in matrix[1]]

    formatted_matrix = _format_matrix(matrix)
    if results[0].get("breakdown_value") is not None:
        breakdown_value = results[0]["breakdown_value"]
        if isinstance(breakdown_value, list):
            breakdown_value = ", ".join(breakdown_value)
        return f"---{breakdown_value}\n{formatted_matrix}"
    return formatted_matrix


def compress_and_format_funnels_results(
    results: list[dict] | list[list[dict]],
    date_from: str,
    date_to: str,
    funnel_step_reference: FunnelStepReference | None = None,
) -> str:
    """
    Compresses and formats funnels results into a LLM-friendly string.

    Example answer:
    ```
    Date range
    Metric|Label 1|Label 2
    Total person count|value1|value2
    Conversion rate|value1|value2
    Drop-off rate|value1|value2
    Average conversion time|value1|value2
    Median conversion time|value1|value2
    ```
    """
    funnel_step_reference = funnel_step_reference or FunnelStepReference.TOTAL

    if len(results) == 0:
        return "No data recorded for this time period."

    matrixes = []
    if isinstance(results[0], list):
        for result in results:
            matrixes.append(_format_funnels_results(cast(list[dict], result), funnel_step_reference))
    else:
        matrixes.append(_format_funnels_results(cast(list[dict], results), funnel_step_reference))

    conversion_type_hint = 'Conversion and drop-off rates are calculated in overall. For example, "Conversion rate: 9%" means that 9% of users from the first step completed the funnel.'
    if funnel_step_reference == FunnelStepReference.PREVIOUS:
        conversion_type_hint = "Conversion and drop-off rates are relative to the previous steps. For example, 'Conversion rate: 90%' means that 90% of users from the previous step completed the funnel."

    joined_matrixes = "\n\n".join(matrixes)
    return f"Date range: {date_from} to {date_to}\n\n{joined_matrixes}\n\n{conversion_type_hint}"


def compress_and_format_retention_results(results: list[dict], period: RetentionPeriod | None = None) -> str:
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
    period = period or RetentionPeriod.DAY

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
    return f"Date range: {date_from} to {date_to}\nGranularity: {period}\n{_format_matrix(matrix)}"

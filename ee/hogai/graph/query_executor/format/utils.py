import datetime
from math import floor
from typing import Any, Optional, Union

from posthog.hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)


def format_matrix(matrix: list[list[str]]) -> str:
    lines: list[str] = []
    for row in matrix:
        lines.append("|".join(row))

    return "\n".join(lines).strip()


def format_number(value: Any) -> str:
    if value is None:
        return "N/A"

    try:
        num = float(value)
        if num.is_integer():
            return str(int(num))
        return f"{num:.5f}".rstrip("0")
    except ValueError:
        return str(value)


def format_percentage(value: float | int) -> str:
    num = float(value) * 100
    formatted = f"{num:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def format_duration(
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
        return f"-{format_duration(-d, max_units, seconds_precision, seconds_fixed)}"

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


def format_date(date: datetime.date) -> str:
    return date.strftime("%Y-%m-%d")


def strip_datetime_seconds(date: str) -> str:
    return datetime.datetime.fromisoformat(date).strftime("%Y-%m-%d %H:%M" if ":" in date else "%Y-%m-%d")


def replace_breakdown_labels(name: str) -> str:
    return name.replace(BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_OTHER_DISPLAY).replace(
        BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_NULL_DISPLAY
    )

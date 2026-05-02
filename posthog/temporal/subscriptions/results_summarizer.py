import math
from typing import Any

from structlog import get_logger

LOGGER = get_logger(__name__)

MAX_SUMMARY_LENGTH = 2000


def build_results_summary(
    query_kind: str,
    results: list[Any] | None,
    columns: list[str] | None = None,
) -> str:
    if not results:
        return "No results"

    summarizer = _SUMMARIZERS.get(query_kind)
    if summarizer is not None:
        text = summarizer(results)
    else:
        text = _summarize_generic(results, columns)
    if len(text) > MAX_SUMMARY_LENGTH:
        text = text[:MAX_SUMMARY_LENGTH] + "\n... (truncated)"
    return text


def _summarize_trends(results: list[dict[str, Any]]) -> str:
    if _looks_like_boxplot_trend(results):
        return _summarize_boxplot_trend(results)

    lines: list[str] = []
    for series in results:
        label = series.get("label", "Unknown")
        data = series.get("data", [])
        aggregated_value = series.get("aggregated_value")

        if data and isinstance(data, list):
            numeric = [v for v in data if isinstance(v, (int, float)) and math.isfinite(v)]
            if numeric:
                latest = numeric[-1]
                avg = sum(numeric) / len(numeric)
                trend = _trend_direction(numeric)
                lines.append(
                    f"- {label}: latest={_fmt(latest)}, avg={_fmt(avg)}, "
                    f"min={_fmt(min(numeric))}, max={_fmt(max(numeric))}, trend={trend} ({len(numeric)} points)"
                )
                continue

        if aggregated_value is not None:
            lines.append(f"- {label}: total={_fmt(aggregated_value)}")
        elif series.get("count") is not None and series["count"] != 0:
            lines.append(f"- {label}: count={_fmt(series['count'])}")
        else:
            lines.append(f"- {label}: (no data)")

    return "\n".join(lines) if lines else "No trend series"


def _looks_like_boxplot_trend(results: list[dict[str, Any]]) -> bool:
    # Boxplot TrendsQuery results have one row per (series × time bucket) with
    # quantile stats (median/min/max/p25/p75) and no `data` array.
    if not results or not isinstance(results[0], dict):
        return False
    first = results[0]
    return "median" in first and "data" not in first


def _summarize_boxplot_trend(results: list[dict[str, Any]]) -> str:
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        label = row.get("series_label") or row.get("label") or "Unknown"
        by_series.setdefault(label, []).append(row)

    lines: list[str] = []
    for label, rows in by_series.items():
        medians = [
            r["median"] for r in rows if isinstance(r.get("median"), (int, float)) and math.isfinite(r["median"])
        ]
        if not medians:
            lines.append(f"- {label}: (no data)")
            continue
        maxes = [r["max"] for r in rows if isinstance(r.get("max"), (int, float)) and math.isfinite(r["max"])]
        mins = [r["min"] for r in rows if isinstance(r.get("min"), (int, float)) and math.isfinite(r["min"])]
        trend = _trend_direction(medians)
        lines.append(
            f"- {label} (boxplot): median latest={_fmt(medians[-1])}, "
            f"median avg={_fmt(sum(medians) / len(medians))}, "
            f"overall min={_fmt(min(mins) if mins else medians[-1])}, "
            f"overall max={_fmt(max(maxes) if maxes else medians[-1])}, "
            f"median trend={trend} ({len(medians)} points)"
        )

    return "\n".join(lines) if lines else "No trend series"


def _summarize_funnels(results: list[Any]) -> str:
    lines: list[str] = []

    steps = results
    if results and isinstance(results[0], list):
        steps = results[0]

    for i, step in enumerate(steps):
        name = step.get("name", step.get("custom_name", f"Step {i + 1}"))
        count = step.get("count", 0)
        conversion = step.get("conversion_rate")
        if conversion is not None:
            lines.append(f"- Step {i + 1} ({name}): count={_fmt(count)}, conversion={_fmt(conversion)}%")
        else:
            lines.append(f"- Step {i + 1} ({name}): count={_fmt(count)}")

    return "\n".join(lines) if lines else "No funnel steps"


def _summarize_retention(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, cohort in enumerate(results[:10]):
        label = cohort.get("label", cohort.get("date", f"Cohort {i}"))
        values = cohort.get("values", [])
        if values:
            initial = values[0].get("count", 0) if isinstance(values[0], dict) else values[0]
            final = values[-1].get("count", 0) if isinstance(values[-1], dict) else values[-1]
            retention_pct = (final / initial * 100) if initial > 0 else 0
            lines.append(f"- {label}: initial={_fmt(initial)}, final={_fmt(final)}, retention={_fmt(retention_pct)}%")
        else:
            lines.append(f"- {label}: (no values)")
    if len(results) > 10:
        lines.append(f"... and {len(results) - 10} more cohorts")
    return "\n".join(lines) if lines else "No retention cohorts"


def _summarize_generic(results: list[Any], columns: list[str] | None = None) -> str:
    """Fallback for query kinds without a dedicated summarizer.

    Handles both row shapes we see in practice:
    - dict rows (most PostHog query results): skip known noisy keys, join the rest.
    - list/tuple rows (HogQL / DataVisualizationNode): label each value with the
      corresponding entry from `columns` when provided, falling back to
      position-indexed `colN` names when a column list is unavailable or shorter
      than the row.
    Any other shape falls back to str() so a surprising result shape produces a
    usable summary instead of an AttributeError that kills the whole activity.
    """
    lines: list[str] = []
    for i, row in enumerate(results[:20]):
        parts: list[str] = []
        if isinstance(row, dict):
            for key, val in row.items():
                if key in ("data", "values", "days", "labels", "timestamps"):
                    continue
                parts.append(f"{key}={val}")
        elif isinstance(row, (list, tuple)):
            for col_index, val in enumerate(row):
                label = _column_label(columns, col_index)
                parts.append(f"{label}={val}")
        else:
            # Emit a signal rather than silently producing an ok-ish summary — if a
            # new shape appears in practice we find out from logs, not from a user.
            LOGGER.info(
                "subscription_summary.unexpected_row_shape",
                row_type=type(row).__name__,
            )
            parts.append(str(row))
        if parts:
            lines.append(f"- Row {i + 1}: {', '.join(parts)}")
    if len(results) > 20:
        lines.append(f"... and {len(results) - 20} more rows")
    return "\n".join(lines) if lines else "No results data"


def _column_label(columns: list[str] | None, index: int) -> str:
    if columns and index < len(columns) and columns[index].strip():
        return columns[index]
    return f"col{index}"


def _trend_direction(values: list[float | int]) -> str:
    if len(values) < 2:
        return "stable"
    first_half = values[: len(values) // 2]
    second_half = values[len(values) // 2 :]
    avg_first = sum(first_half) / len(first_half) if first_half else 0
    avg_second = sum(second_half) / len(second_half) if second_half else 0
    if avg_first == 0:
        if avg_second > 0:
            return "up"
        elif avg_second < 0:
            return "down"
        return "stable"
    pct_change = (avg_second - avg_first) / abs(avg_first) * 100
    if pct_change > 5:
        return "up"
    elif pct_change < -5:
        return "down"
    return "stable"


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "N/A"
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return f"{value:,}"


_SUMMARIZERS: dict[str, Any] = {
    "TrendsQuery": _summarize_trends,
    "FunnelsQuery": _summarize_funnels,
    "RetentionQuery": _summarize_retention,
    "LifecycleQuery": _summarize_trends,
    "StickinessQuery": _summarize_trends,
}

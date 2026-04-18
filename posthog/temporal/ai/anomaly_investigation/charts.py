"""Matplotlib chart rendering for the anomaly investigation agent.

Renders a compact PNG of the alert's metric over time, with the detector's
anomaly points highlighted. The PNG is base64-encoded and attached to the
first HumanMessage so the multimodal model can reason visually about the
shape of the anomaly (spike, cliff, gradual drift, seasonality, etc.) before
it spends any tool-call budget.
"""

from __future__ import annotations

import io
import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

CHART_WIDTH_IN = 8.0
CHART_HEIGHT_IN = 3.5
CHART_DPI = 110


def render_series_chart(
    *,
    dates: list[str],
    values: list[float],
    triggered_indices: list[int] | None = None,
    scores: list[float] | None = None,
    title: str = "",
) -> bytes | None:
    """Return a PNG of the series with anomaly points marked, or None on failure.

    Best-effort: if matplotlib can't render (empty data, backend error, etc.),
    log and return None so the investigation continues text-only.
    """
    if not dates or not values or len(dates) != len(values):
        return None

    try:
        # Non-interactive backend — safe in a Temporal activity worker thread.
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception:
        logger.exception("anomaly_investigation.chart_import_failed")
        return None

    try:
        fig, ax = plt.subplots(figsize=(CHART_WIDTH_IN, CHART_HEIGHT_IN), dpi=CHART_DPI)
        x = list(range(len(values)))

        ax.plot(x, values, color="#1d4ed8", linewidth=1.8, marker="o", markersize=3, label="Metric")

        if triggered_indices:
            anomaly_x = [i for i in triggered_indices if 0 <= i < len(values)]
            anomaly_y = [values[i] for i in anomaly_x]
            if anomaly_x:
                ax.scatter(anomaly_x, anomaly_y, color="#dc2626", s=80, zorder=5, label="Anomaly", edgecolors="white")

        if scores and len(scores) == len(values):
            ax2 = ax.twinx()
            ax2.plot(x, scores, color="#f59e0b", linewidth=1.0, linestyle="--", alpha=0.7, label="Score")
            ax2.set_ylabel("Score", fontsize=9, color="#92400e")
            ax2.tick_params(axis="y", labelsize=8, colors="#92400e")
            ax2.set_ylim(0, max(1.05, max(scores) * 1.05))

        tick_stride = max(1, len(dates) // 8)
        ax.set_xticks(x[::tick_stride])
        ax.set_xticklabels([_short_date(d) for d in dates[::tick_stride]], rotation=0, fontsize=8)
        ax.set_xlabel("")
        ax.set_ylabel("Value", fontsize=9)
        ax.tick_params(axis="y", labelsize=8)
        if title:
            ax.set_title(title, fontsize=10, loc="left")
        ax.grid(True, alpha=0.25, linewidth=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.legend(loc="upper left", fontsize=8, frameon=False)

        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        logger.exception("anomaly_investigation.chart_render_failed")
        return None


def png_to_b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")


def _short_date(raw: Any) -> str:
    """Return a short label like 'Apr 1' or '14:00' for x-tick display."""
    s = str(raw)
    # Drop time-of-day zeros to keep ticks compact (e.g. "2026-04-01 00:00:00" -> "Apr 1").
    if " " in s:
        date_part, time_part = s.split(" ", 1)
        if time_part.startswith("00:00"):
            return _mmdd(date_part)
        return time_part[:5]
    return _mmdd(s)


def _mmdd(date_str: str) -> str:
    parts = date_str.split("-")
    if len(parts) != 3:
        return date_str
    try:
        month = int(parts[1])
        day = int(parts[2][:2])
    except ValueError:
        return date_str
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if 1 <= month <= 12:
        return f"{months[month - 1]} {day}"
    return date_str

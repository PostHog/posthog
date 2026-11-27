"""The lines an investigated insight alert notification states.

The insight stack and the alerts platform both send these, so one definition keeps the two word
for word the same.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from posthog.dataclasses import frozen
from posthog.tasks.alerts.utils import InvestigationSummaryLine, investigation_summary_teaser
from posthog.utils import absolute_uri

VERDICT_LABELS: Final = {
    "true_positive": "True positive",
    "false_positive": "False positive",
    "inconclusive": "Inconclusive",
}

SAFETY_NET_LINE: Final = "(Investigation agent did not complete before the notification grace period expired.)"


@frozen
class InvestigationBreaches:
    lines: list[str]
    summary: InvestigationSummaryLine | None


def notebook_url(notebook_short_id: str) -> str:
    return absolute_uri(f"/notebooks/{notebook_short_id}")


def _anomaly_head(triggered_dates: Sequence[str], value: float | None) -> str:
    if triggered_dates:
        if len(triggered_dates) == 1:
            return f"Anomaly detected on {triggered_dates[0]}."
        return f"Anomaly detected from {triggered_dates[0]} to {triggered_dates[-1]}."
    if value is not None:
        return f"Calculated value at fire: {value}."
    return "Anomaly detected."


def verdict_breaches(
    *,
    triggered_dates: Sequence[str],
    value: float | None,
    verdict: str | None,
    previous_verdict: str | None,
    summary: str,
    notebook_short_id: str | None,
) -> InvestigationBreaches:
    """The breach lines of a notification sent once the agent reached its verdict.

    The summary line holds a plain-text teaser. Email renders the full Markdown in its place.
    """
    lines: list[str] = []
    if previous_verdict and verdict and verdict != previous_verdict:
        lines.append(
            f"Investigation verdict changed from {VERDICT_LABELS.get(previous_verdict, previous_verdict)} "
            f"to {VERDICT_LABELS.get(verdict, verdict)} while this alert keeps firing."
        )
    lines.append(_anomaly_head(triggered_dates, value))

    verdict_label = VERDICT_LABELS.get(verdict or "", "")
    if verdict_label:
        lines.append(f"Investigation verdict: {verdict_label}.")
    summary_line = None
    teaser = investigation_summary_teaser(summary)
    if teaser:
        summary_line = InvestigationSummaryLine(index=len(lines), markdown=summary)
        lines.append(teaser)
    if notebook_short_id:
        lines.append(f"See {notebook_url(notebook_short_id)} for the full investigation.")
    return InvestigationBreaches(lines=lines, summary=summary_line)


def safety_net_breaches(*, triggered_dates: Sequence[str], value: float | None) -> list[str]:
    """Minimal breach description for a notification the safety net sent without a verdict."""
    return [_anomaly_head(triggered_dates, value), SAFETY_NET_LINE]

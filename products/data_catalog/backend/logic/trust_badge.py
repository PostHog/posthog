"""The trust badge an agent puts above an answer that a canonical metric run produced.

The server decides from the stored status and the computed drift, so an agent cannot give a
proposed or drifted metric the badge.
"""

from typing import Optional

from posthog.models import Team
from posthog.utils import absolute_uri

from ..facade.enums import APPROVED_ICON, MetricStatus
from ..models import Metric


def build_trust_badge(team: Team, metric: Metric, is_drifted: bool) -> Optional[str]:
    if metric.status != MetricStatus.APPROVED or is_drifted:
        return None
    link = f"[{_markdown_label(metric.display_name or metric.name)}]({_metric_url(team, metric)})"
    return f"{APPROVED_ICON} **From your data catalog**: {link}, an approved definition {_reviewed_by(metric)}"


def _reviewed_by(metric: Metric) -> str:
    approver = metric.approved_by
    name = f"{approver.first_name} {approver.last_name}".strip() if approver else ""
    reviewer = name or "your team"
    if metric.approved_at is None:
        return f"reviewed by {reviewer}"
    return f"reviewed by {reviewer} on {metric.approved_at:%b} {metric.approved_at.day}, {metric.approved_at.year}"


def _metric_url(team: Team, metric: Metric) -> str:
    return absolute_uri(f"/project/{team.id}/data-catalog/metrics/{metric.name}")


def _markdown_label(text: str) -> str:
    return text.replace("[", "(").replace("]", ")")

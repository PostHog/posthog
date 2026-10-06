"""The trust label an agent puts on a number that a metric run produced.

The server picks the tier from the stored status and the computed drift, so an agent cannot give a
proposed or drifted metric the approved label.
"""

from posthog.models import Team
from posthog.utils import absolute_uri

from ..facade.enums import APPROVED_ICON, UNAPPROVED_ICON, MetricStatus, MetricTrustTier
from ..models import Metric


def trust_tier(metric: Metric, is_drifted: bool) -> MetricTrustTier:
    if metric.status != MetricStatus.APPROVED:
        return MetricTrustTier.PROPOSED
    if is_drifted:
        return MetricTrustTier.DRIFTED
    return MetricTrustTier.APPROVED


def build_provenance(team: Team, metric: Metric, is_drifted: bool) -> dict:
    tier = trust_tier(metric, is_drifted)
    link = f"[{_markdown_label(metric.display_name or metric.name)}]({_metric_url(team, metric)})"
    if tier == MetricTrustTier.APPROVED:
        label = f"{APPROVED_ICON} **From your data catalog**: {link}, approved definition, {_reviewed_by(metric)}"
    elif tier == MetricTrustTier.DRIFTED:
        label = f"{UNAPPROVED_ICON} **Definition needs review**: {link} is approved, but no longer matches its source insight"
    else:
        label = f"{UNAPPROVED_ICON} **Proposed definition**: {link} is in your data catalog, not yet approved"
    return {"tier": tier.value, "label": label}


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

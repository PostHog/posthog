"""What a platform message about an investigated insight firing says about its investigation.

The insight stack words a firing from its `AlertCheck`. The platform records no check, so the
describer, the Slack renderer and the legacy-event emitter read the evaluation's
`InsightAlertInvestigation` row, and the platform's hold on its delivery, as the message goes out.

The verdict arrives after the firing is recorded, so it cannot sit on the history row the message
is built from.
"""

from __future__ import annotations

import structlog

from posthog.dataclasses import frozen
from posthog.tasks.alerts.investigation_wording import notebook_url, safety_net_breaches, verdict_breaches
from posthog.tasks.alerts.utils import investigation_summary_teaser

from products.alerts.backend.models.alert import InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_alert_wording import VERDICT_CHANGED_KIND, announces_firing
from products.alerts.backend.platform_investigation import investigated_evaluation_key
from products.alerts_platform.backend.facade.api import hold_released_by
from products.alerts_platform.backend.facade.contracts import AnnouncedTransition, HeldDeliveryAddress
from products.alerts_platform.backend.facade.enums import HoldReleasedBy

logger = structlog.get_logger(__name__)


@frozen
class FiringInvestigation:
    """An investigation of a firing, in the fields a message states."""

    status: str
    verdict: str | None
    chat_summary: str | None
    # The lines that replace the firing's own breaches. None keeps the firing's breaches.
    breaches: tuple[str, ...] | None
    # Set only when the message carries the verdict, as the insight stack links the notebook then.
    notebook_url: str | None


def firing_breaches(transition: AnnouncedTransition, investigation: FiringInvestigation | None) -> list[str]:
    """The breach lines a firing states: its investigation's, or the ones its check recorded."""
    if investigation is not None and investigation.breaches is not None:
        return list(investigation.breaches)
    return transition.source_detail.get("breaches") or []


def firing_investigation(team_id: int, transition: AnnouncedTransition) -> FiringInvestigation | None:
    """The investigation of the firing a transition announces, or None when it had none.

    Never raises: a failed read costs the message its investigation lines, never the message.
    """
    if not announces_firing(transition) or not transition.configuration_id:
        return None
    try:
        return _read(team_id, transition)
    except Exception:
        logger.exception("alerts_insight_investigation_read_failed", configuration_id=transition.configuration_id)
        return None


def _read(team_id: int, transition: AnnouncedTransition) -> FiringInvestigation | None:
    follow_up = transition.kind == VERDICT_CHANGED_KIND
    evaluation_key = investigated_evaluation_key(transition.evaluation_key) if follow_up else transition.evaluation_key
    rows = InsightAlertInvestigation.objects.for_team(team_id).filter(configuration_id=transition.configuration_id)
    row = rows.filter(evaluation_key=evaluation_key).values_list(
        "status",
        "verdict",
        "summary",
        "notebook__short_id",
        "evaluated",
        "kind",
        "episode_started_at",
        "created_at",
    )
    found = row.first()
    if found is None:
        return None
    status, verdict, summary, notebook_short_id, evaluated, kind, episode_started_at, created_at = found
    # A refused claim investigated nothing, so its firing reads as one the agent never saw.
    if status == InvestigationStatus.SKIPPED:
        return None

    released_by = (
        None
        if follow_up
        else hold_released_by(
            HeldDeliveryAddress(
                team_id=team_id, configuration_id=transition.configuration_id, evaluation_key=evaluation_key
            )
        )
    )
    triggered_dates = [str(date) for date in evaluated.get("triggered_dates") or []]
    value = evaluated.get("value")
    breaches: tuple[str, ...] | None = None
    link: str | None = None
    # Only the agent's verdict rewords a firing. A metrics investigation explains the firing beside
    # its own breaches, so its release keeps them, also when it failed.
    agent = kind == InsightAlertInvestigation.Kind.AGENT
    if follow_up or (agent and released_by == HoldReleasedBy.VERDICT):
        previous_verdict = (
            rows.filter(episode_started_at=episode_started_at, created_at__lt=created_at, verdict__isnull=False)
            .order_by("-created_at")
            .values_list("verdict", flat=True)
            .first()
            if verdict
            else None
        )
        breaches = tuple(
            verdict_breaches(
                triggered_dates=triggered_dates,
                value=value,
                verdict=verdict,
                previous_verdict=previous_verdict,
                summary=summary or "",
                notebook_short_id=notebook_short_id,
            ).lines
        )
        link = notebook_url(notebook_short_id) if notebook_short_id else None
    elif agent and released_by == HoldReleasedBy.SAFETY_NET:
        breaches = tuple(safety_net_breaches(triggered_dates=triggered_dates, value=value))
    elif not agent and status == InvestigationStatus.DONE and summary:
        # Every channel reads the breaches, so the explanation goes after them, as the agent's teaser does.
        breaches = (*(str(line) for line in transition.source_detail.get("breaches") or []), summary)

    return FiringInvestigation(
        status=status,
        verdict=verdict,
        # The agent writes Markdown, which chat shows as is, so it gets the teaser. The metrics
        # investigation writes plain text.
        chat_summary=investigation_summary_teaser(summary) if kind == InsightAlertInvestigation.Kind.AGENT else summary,
        breaches=breaches,
        notebook_url=link,
    )

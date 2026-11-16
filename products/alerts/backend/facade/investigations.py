"""What the investigation agent writes back for a platform evaluation of an insight alert.

Apart from `facade.api`, which the insight stack's task helpers import, because these import them.
"""

from uuid import UUID

from products.alerts.backend import investigation_release
from products.alerts.backend.facade.contracts import InvestigationRelease
from products.alerts.backend.investigation_release import verdict_change_is_news
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.investigation import InsightAlertInvestigation

__all__ = [
    "finish_investigation",
    "mark_investigation_failed",
    "mark_investigation_running",
    "verdict_change_is_news",
]


def _investigation(team_id: int, investigation_id: UUID) -> InsightAlertInvestigation:
    return InsightAlertInvestigation.objects.for_team(team_id).get(id=investigation_id)


def mark_investigation_running(team_id: int, investigation_id: UUID) -> None:
    """Marks the investigation as running and holds its firing for the running grace."""
    investigation_release.mark_investigation_running(_investigation(team_id, investigation_id))


def mark_investigation_failed(team_id: int, investigation_id: UUID, reason: str) -> None:
    """Records the investigation's failure and leaves its firing to the platform's safety net."""
    investigation_release.mark_investigation_failed(_investigation(team_id, investigation_id), reason)


def finish_investigation(
    team_id: int,
    alert_id: UUID,
    investigation_id: UUID,
    *,
    verdict: str | None,
    summary: str | None,
    notebook_id: UUID | None,
) -> InvestigationRelease:
    """Records the investigation's verdict and releases its held firing by it. Safe to repeat."""
    return investigation_release.finish_investigation(
        AlertConfiguration.objects.get(team_id=team_id, id=alert_id),
        _investigation(team_id, investigation_id),
        verdict=verdict,
        summary=summary,
        notebook_id=notebook_id,
    )

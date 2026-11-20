from posthog.models.team import Team
from posthog.organization_offboarding_types import OffboardingResource

from products.alerts.backend.facade.api import enabled_alerts_created_by


class AlertOffboarding:
    def __init__(self, organization_id: str, user_id: int) -> None:
        self.organization_id = organization_id
        self.user_id = user_id

    def resources(self) -> list[OffboardingResource]:
        project_names = dict(Team.objects.filter(organization_id=self.organization_id).values_list("id", "name"))
        return [
            OffboardingResource(
                id=f"alert:{alert.id}",
                resource_id=str(alert.id),
                kind="alert",
                name=alert.name or "Untitled alert",
                team_id=alert.team_id,
                project_name=project_names[alert.team_id],
                created_at=alert.created_at,
                url=f"/project/{alert.team_id}/alerts?alert_type=insights&alert_id={alert.id}",
            )
            for alert in enabled_alerts_created_by(team_ids=list(project_names), user_id=self.user_id)
        ]

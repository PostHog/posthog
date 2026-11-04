from django.db.models import QuerySet

from posthog.organization_offboarding_types import OffboardingResource

from products.alerts.backend.models.alert import AlertConfiguration


class AlertOffboarding:
    def __init__(self, organization_id: str, user_id: int) -> None:
        self.organization_id = organization_id
        self.user_id = user_id

    def _alerts(self) -> QuerySet[AlertConfiguration]:
        return AlertConfiguration.objects.filter(
            team__organization_id=self.organization_id,
            created_by_id=self.user_id,
            enabled=True,
            insight__deleted=False,
        )

    def resources(self) -> list[OffboardingResource]:
        return [
            OffboardingResource(
                id=f"alert:{alert.pk}",
                resource_id=str(alert.pk),
                kind="alert",
                name=alert.name or "Untitled alert",
                team_id=alert.team_id,
                project_name=alert.team.name,
                created_at=alert.created_at,
                url=f"/project/{alert.team_id}/alerts?alert_type=insights&alert_id={alert.pk}",
            )
            for alert in self._alerts().select_related("team")
        ]

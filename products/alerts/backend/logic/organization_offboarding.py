from functools import partial

from django.db import transaction
from django.db.models import QuerySet

from posthog.organization_offboarding_types import OffboardingResource

from products.alerts.backend.insight_alert_state_machine import apply_disable
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.api import disable_configurations
from products.alerts_platform.backend.facade.contracts import SourceKind


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
                kind="alert",
                name=alert.name or "Untitled alert",
                team_id=alert.team_id,
                project_name=alert.team.name,
                created_at=alert.created_at,
                url=f"/project/{alert.team_id}/alerts?alert_type=insights&alert_id={alert.pk}",
            )
            for alert in self._alerts().select_related("team")
        ]

    def disable(self, keep: set[str]) -> None:
        for alert in self._alerts():
            if f"alert:{alert.pk}" not in keep:
                alert.save(update_fields=apply_disable(alert))
                if alert.platform_owned:
                    # The platform writer imports Temporal workflows, which import the organization API during startup.
                    from products.alerts.backend.platform_ownership import write_moved_alert_edit

                    write_moved_alert_edit(team_id=alert.team_id, alert_id=alert.id, snooze_changed=False)
                else:
                    transaction.on_commit(
                        partial(
                            disable_configurations,
                            SourceKind.INSIGHT,
                            team_id=alert.team_id,
                            legacy_configuration_ids=[alert.id],
                        ),
                        robust=True,
                    )

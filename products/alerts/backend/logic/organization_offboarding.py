from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from posthog.organization_offboarding_types import OffboardingResource

from products.alerts.backend.insight_alert_state_machine import apply_disable, apply_enable
from products.alerts.backend.llm_detector_limits import LLMAlertWrite, admit_llm_alert_write
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
            for alert in self._alerts().filter(enabled=True).select_related("team")
        ]

    def update(self, resource_id: str, enabled: bool) -> None:
        identifier = AlertConfiguration._meta.pk.to_python(resource_id.removeprefix("alert:"))
        alert = self._alerts().select_for_update().filter(pk=identifier).first()
        if alert is None:
            raise ValidationError("Alert not found for this member.")
        if alert.enabled == enabled:
            return
        if enabled:
            refusal = admit_llm_alert_write(
                LLMAlertWrite(
                    team_id=alert.team_id,
                    organization=alert.team.organization,
                    principal=alert.created_by,
                    detector_config=alert.detector_config,
                    enabled=True,
                    calculation_interval=alert.calculation_interval,
                    existing=alert,
                )
            )
            if refusal:
                raise ValidationError(refusal.message)
        alert.save(update_fields=apply_enable(alert) if enabled else apply_disable(alert))
        if alert.platform_owned:
            # The platform writer imports Temporal workflows, which import the organization API during startup.
            from products.alerts.backend.platform_ownership import write_moved_alert_edit

            write_moved_alert_edit(team_id=alert.team_id, alert_id=alert.id, snooze_changed=False)
        elif not enabled:
            transaction.on_commit(
                partial(
                    disable_configurations,
                    SourceKind.INSIGHT,
                    team_id=alert.team_id,
                    legacy_configuration_ids=[alert.id],
                ),
                robust=True,
            )

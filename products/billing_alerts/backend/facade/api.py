from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.alerts.backend.facade.api import (
    AlertDestinationData,
    DestinationType,
    build_alert_destination_config,
    create_alert_destination_hog_functions,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
    validate_destination_data,
)

from ..alert_destinations import (
    BILLING_ALERT_EVENT_IDS,
    BILLING_ALERT_SLACK_CONTEXT_ELEMENTS,
    BILLING_DESTINATION_TYPES,
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    EventKind,
    destination_groups_for_alerts,
)
from ..logic.notifications import evaluate_and_dispatch_billing_alert
from ..logic.state_machine import (
    apply_disable,
    apply_enable,
    apply_outcome,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    billing_alert_snapshot,
    next_billing_alert_check_at,
)
from ..models import BillingAlertConfiguration, BillingAlertEvent, validate_threshold_configuration


@dataclass(frozen=True)
class BillingAlertDispatchResult:
    event: BillingAlertEvent
    dispatched_destinations: int


class BillingAlertExecutionTeamUnavailable(Exception):
    """Raised when an organization has no team to use for destination execution."""


def initialize_billing_alert_lifecycle(alert: BillingAlertConfiguration) -> None:
    """Apply lifecycle state implied by a newly created alert configuration."""
    snapshot = billing_alert_snapshot(alert)

    if not alert.enabled:
        update_fields = apply_outcome(alert, apply_disable(snapshot))
    elif alert.snoozed_until is not None:
        update_fields = apply_outcome(alert, apply_snooze(snapshot))
    else:
        return

    alert.save(update_fields=[*update_fields, "updated_at"])


def apply_billing_alert_configuration_lifecycle(
    alert: BillingAlertConfiguration,
    *,
    enabled_change: bool | None,
    snoozed_until_provided: bool,
    snoozed_until: datetime | None,
    threshold_changed: bool,
) -> None:
    """Apply one control-plane change through the shared lifecycle adapter."""
    snapshot = billing_alert_snapshot(alert)

    if threshold_changed:
        apply_outcome(alert, apply_threshold_change(snapshot))
        snapshot = billing_alert_snapshot(alert)

    if enabled_change is True:
        apply_outcome(alert, apply_enable(snapshot))
        snapshot = billing_alert_snapshot(alert)
    elif enabled_change is False:
        apply_outcome(alert, apply_disable(snapshot))
        snapshot = billing_alert_snapshot(alert)

    if snoozed_until_provided:
        if snoozed_until is None:
            apply_outcome(alert, apply_unsnooze(snapshot))
        else:
            apply_outcome(alert, apply_snooze(snapshot))


def reschedule_billing_alert_configuration(
    alert: BillingAlertConfiguration,
    *,
    configuration_changed: bool,
) -> None:
    if not configuration_changed:
        return
    alert.configuration_revision += 1
    alert.pending_evaluation_date = None
    alert.retry_attempt_count = 0
    alert.next_check_at = next_billing_alert_check_at(alert, timezone.now())
    alert.save(
        update_fields=[
            "configuration_revision",
            "pending_evaluation_date",
            "retry_attempt_count",
            "next_check_at",
            "updated_at",
        ]
    )


def execution_team_for_organization(organization_id: UUID, preferred_team: Team | None) -> Team:
    if preferred_team and preferred_team.organization_id == organization_id:
        return preferred_team

    team = Team.objects.filter(organization_id=organization_id).order_by("id").first()
    if team is None:
        raise BillingAlertExecutionTeamUnavailable("This organization does not have an execution team.")
    return team


def visible_events_for_alert(alert: BillingAlertConfiguration) -> QuerySet[BillingAlertEvent]:
    return BillingAlertEvent.objects.filter(claim__alert=alert).select_related("claim").order_by("-created_at")


def evaluate_and_dispatch_alert(alert: BillingAlertConfiguration) -> BillingAlertDispatchResult:
    event, dispatched = evaluate_and_dispatch_billing_alert(alert)
    return BillingAlertDispatchResult(event=event, dispatched_destinations=dispatched)


def delete_alert_and_destinations(alert: BillingAlertConfiguration) -> None:
    with transaction.atomic():
        if alert.team_id is not None:
            soft_delete_all_alert_destinations(
                team_id=alert.execution_team_id,
                alert_id=str(alert.id),
                allowed_event_ids=BILLING_ALERT_EVENT_IDS,
            )
        alert.delete()


def destinations_for_alerts(alerts: list[BillingAlertConfiguration]) -> dict[str, list[dict[str, Any]]]:
    alert_ids = {str(alert.id) for alert in alerts}
    team_ids = {alert.execution_team_id for alert in alerts if alert.team_id is not None}
    if not alert_ids or not team_ids:
        return {}

    groups = destination_groups_for_alerts(team_ids=team_ids, alert_ids=alert_ids)
    required_event_ids = set(BILLING_ALERT_EVENT_IDS)
    return {
        alert_id: [
            {"type": destination_type, "hog_function_ids": sorted(hog_function_ids.values())}
            for destination_type, hog_function_ids in sorted(groups.get(alert_id, {}).items())
            if set(hog_function_ids) == required_event_ids
        ]
        for alert_id in alert_ids
    }


def slack_integration_belongs_to_team(*, integration_id: int, team_id: int) -> bool:
    return Integration.objects.filter(
        id=integration_id,
        team_id=team_id,
        kind=Integration.IntegrationKind.SLACK,
    ).exists()


def create_destination(alert: BillingAlertConfiguration, *, request: Any, data: dict[str, Any]) -> list[UUID]:
    destination_data = cast(AlertDestinationData, data)
    validate_destination_data(destination_data, allowed_destination_types=BILLING_DESTINATION_TYPES)
    destination_data["type"] = DestinationType(data["type"])
    if destination_data["type"] == DestinationType.SLACK and not slack_integration_belongs_to_team(
        integration_id=destination_data["slack_workspace_id"],
        team_id=alert.execution_team_id,
    ):
        raise DRFValidationError(
            {"slack_workspace_id": "Slack integration does not belong to this billing alert execution team."}
        )
    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(
            pk=alert.pk,
            organization_id=alert.organization_id,
        )
        if locked_alert.team is None:
            raise DRFValidationError({"type": "This billing alert does not have an execution team."})
        existing_types = {
            destination["type"] for destination in destinations_for_alerts([locked_alert]).get(str(locked_alert.id), [])
        }
        if destination_data["type"].value in existing_types:
            raise DRFValidationError({"type": f"A {destination_data['type'].label} destination already exists."})
        configs = [
            build_alert_destination_config(
                team=locked_alert.team,
                spec=EVENT_KIND_CONFIG[kind],
                alert_id=str(locked_alert.id),
                alert_name=locked_alert.name,
                data=destination_data,
                slack_context_elements=BILLING_ALERT_SLACK_CONTEXT_ELEMENTS,
            )
            for kind in EVENT_KINDS
        ]
        hog_functions = create_alert_destination_hog_functions(configs, request=request)
        return [hog_function.id for hog_function in hog_functions]


def delete_destination(alert: BillingAlertConfiguration, hog_function_ids: list[UUID]) -> None:
    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(
            pk=alert.pk,
            organization_id=alert.organization_id,
        )
        soft_delete_alert_destinations(
            team_id=locked_alert.execution_team_id,
            alert_id=str(locked_alert.id),
            allowed_event_ids=BILLING_ALERT_EVENT_IDS,
            hog_function_ids=hog_function_ids,
        )


def apply_destination_changes(alert: BillingAlertConfiguration, *, request: Any, changes: dict[str, Any]) -> None:
    """Apply complete destination-group changes inside the caller's configuration transaction."""
    for hog_function_ids in changes.get("delete", []):
        delete_destination(alert, hog_function_ids)
    for destination_data in changes.get("create", []):
        create_destination(alert, request=request, data=destination_data)


__all__ = [
    "BILLING_ALERT_EVENT_IDS",
    "BILLING_DESTINATION_TYPES",
    "EVENT_KINDS",
    "BillingAlertDispatchResult",
    "BillingAlertConfiguration",
    "BillingAlertEvent",
    "BillingAlertExecutionTeamUnavailable",
    "EventKind",
    "apply_billing_alert_configuration_lifecycle",
    "apply_destination_changes",
    "create_destination",
    "delete_alert_and_destinations",
    "delete_destination",
    "destinations_for_alerts",
    "evaluate_and_dispatch_alert",
    "execution_team_for_organization",
    "initialize_billing_alert_lifecycle",
    "reschedule_billing_alert_configuration",
    "slack_integration_belongs_to_team",
    "validate_threshold_configuration",
    "visible_events_for_alert",
]

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from posthog.alerting.destinations import (
    AlertDestinationOwnershipError,
    create_alert_destination_hog_functions,
    destination_types_for_alerts as shared_destination_types_for_alerts,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from posthog.models.integration import Integration
from posthog.models.team.team import Team

from ..alert_destinations import EVENT_KINDS, EventKind, build_destination_config
from ..logic.notifications import dispatch_billing_alert_event
from ..logic.state_machine import evaluate_and_record_billing_alert, event_should_dispatch
from ..models import BillingAlertConfiguration, BillingAlertEvent
from .contracts import BillingAlertDispatchResult


class BillingAlertDestinationOwnershipError(Exception):
    """Raised when deleting destinations that do not all belong to an alert."""


class BillingAlertExecutionTeamUnavailable(Exception):
    """Raised when an organization has no team to use for destination execution."""


def billing_alert_configuration_queryset() -> QuerySet[BillingAlertConfiguration]:
    return BillingAlertConfiguration.objects.all()


def execution_team_for_organization(organization_id: UUID, preferred_team: Team | None) -> Team:
    if preferred_team and preferred_team.organization_id == organization_id:
        return preferred_team

    team = Team.objects.filter(organization_id=organization_id).order_by("id").first()
    if team is None:
        raise BillingAlertExecutionTeamUnavailable("This organization does not have an execution team.")
    return team


def visible_events_for_alert(alert: BillingAlertConfiguration) -> QuerySet[BillingAlertEvent]:
    return BillingAlertEvent.objects.filter(alert=alert).order_by("-created_at")


def evaluate_and_dispatch_alert(alert: BillingAlertConfiguration) -> BillingAlertDispatchResult:
    event = evaluate_and_record_billing_alert(alert)
    dispatched = dispatch_billing_alert_event(event) if event_should_dispatch(event) else 0
    return BillingAlertDispatchResult(event=event, dispatched_destinations=dispatched)


def delete_alert_and_destinations(alert: BillingAlertConfiguration) -> None:
    with transaction.atomic():
        soft_delete_all_alert_destinations(team_id=alert.execution_team_id, alert_id=str(alert.id))
        alert.delete()


def destination_types_for_alerts(alerts: list[BillingAlertConfiguration]) -> dict[str, list[str]]:
    return shared_destination_types_for_alerts(
        team_ids={alert.execution_team_id for alert in alerts},
        alert_ids={str(alert.id) for alert in alerts},
    )


def slack_integration_belongs_to_team(*, integration_id: int, team_id: int) -> bool:
    return Integration.objects.filter(
        id=integration_id,
        team_id=team_id,
        kind=Integration.IntegrationKind.SLACK,
    ).exists()


def create_destination(alert: BillingAlertConfiguration, *, request: Any, data: dict[str, Any]) -> list[UUID]:
    configs = [build_destination_config(alert, alert.team, kind, data) for kind in EVENT_KINDS]
    hog_functions = create_alert_destination_hog_functions(configs, request=request)
    return [hog_function.id for hog_function in hog_functions]


def delete_destination(alert: BillingAlertConfiguration, hog_function_ids: list[UUID]) -> None:
    try:
        soft_delete_alert_destinations(
            team_id=alert.execution_team_id,
            alert_id=str(alert.id),
            hog_function_ids=hog_function_ids,
        )
    except AlertDestinationOwnershipError as e:
        raise BillingAlertDestinationOwnershipError from e


__all__ = [
    "EVENT_KINDS",
    "BillingAlertDispatchResult",
    "BillingAlertConfiguration",
    "BillingAlertDestinationOwnershipError",
    "BillingAlertEvent",
    "BillingAlertExecutionTeamUnavailable",
    "EventKind",
    "billing_alert_configuration_queryset",
    "create_destination",
    "delete_alert_and_destinations",
    "delete_destination",
    "destination_types_for_alerts",
    "evaluate_and_dispatch_alert",
    "execution_team_for_organization",
    "slack_integration_belongs_to_team",
    "visible_events_for_alert",
]

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

from ..alert_destinations import (
    DESTINATION_TYPE_BY_TEMPLATE_ID,
    EVENT_KINDS,
    TEMPLATE_ID_BY_DESTINATION_TYPE,
    EventKind,
    build_destination_config,
)
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
        HogFunction.objects.filter(
            team_id=alert.execution_team_id,
            deleted=False,
            template_id__in=list(TEMPLATE_ID_BY_DESTINATION_TYPE.values()),
            filters__properties__contains=[{"key": "alert_id", "value": str(alert.id)}],
        ).update(deleted=True, enabled=False)
        alert.delete()


def destination_types_for_alerts(alerts: list[BillingAlertConfiguration]) -> dict[str, list[str]]:
    alert_ids = {str(alert.id) for alert in alerts}
    team_ids = {alert.execution_team_id for alert in alerts}
    destination_types_by_alert_id: dict[str, set[str]] = {alert_id: set() for alert_id in alert_ids}

    if not alert_ids or not team_ids:
        return {}

    hog_functions = HogFunction.objects.filter(
        team_id__in=team_ids,
        deleted=False,
        template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
    ).values_list("template_id", "filters")

    for template_id, filters in hog_functions:
        if template_id is None:
            continue
        destination_type = DESTINATION_TYPE_BY_TEMPLATE_ID.get(template_id)
        if destination_type is None or not isinstance(filters, dict):
            continue

        properties = filters.get("properties") or []
        if not isinstance(properties, list):
            continue

        for property_filter in properties:
            if not isinstance(property_filter, dict) or property_filter.get("key") != "alert_id":
                continue
            alert_id = str(property_filter.get("value"))
            if alert_id in destination_types_by_alert_id:
                destination_types_by_alert_id[alert_id].add(destination_type)

    return {
        alert_id: sorted(destination_types) for alert_id, destination_types in destination_types_by_alert_id.items()
    }


def slack_integration_belongs_to_team(*, integration_id: int, team_id: int) -> bool:
    return Integration.objects.filter(
        id=integration_id,
        team_id=team_id,
        kind=Integration.IntegrationKind.SLACK,
    ).exists()


def create_destination(alert: BillingAlertConfiguration, *, request: Any, data: dict[str, Any]) -> list[UUID]:
    with transaction.atomic():
        hog_functions = [_build_and_create_hog_function(alert, alert.team, data, kind, request) for kind in EVENT_KINDS]
    return [hog_function.id for hog_function in hog_functions]


def _build_and_create_hog_function(
    alert: BillingAlertConfiguration,
    team: Team,
    data: dict[str, Any],
    kind: EventKind,
    request: Any,
) -> HogFunction:
    config = build_destination_config(alert, team, kind, data)
    destination_team = config.pop("team")
    serializer = HogFunctionSerializer(
        data=config,
        context={"request": request, "get_team": lambda: destination_team, "is_create": True},
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save(team=destination_team)


def delete_destination(alert: BillingAlertConfiguration, hog_function_ids: list[UUID]) -> None:
    with transaction.atomic():
        updated = HogFunction.objects.filter(
            team_id=alert.execution_team_id,
            id__in=hog_function_ids,
            filters__properties__contains=[{"key": "alert_id", "value": str(alert.id)}],
        ).update(deleted=True, enabled=False)
        if updated != len(hog_function_ids):
            raise BillingAlertDestinationOwnershipError


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

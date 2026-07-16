from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

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
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

from ..alert_destinations import (
    BILLING_ALERT_EVENT_IDS,
    BILLING_ALERT_SLACK_CONTEXT_ELEMENTS,
    BILLING_DESTINATION_TYPES,
    DESTINATION_TYPE_BY_TEMPLATE_ID,
    EVENT_KIND_CONFIG,
    EVENT_KINDS,
    EventKind,
)
from ..logic.notifications import evaluate_and_dispatch_billing_alert
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
    event, dispatched = evaluate_and_dispatch_billing_alert(alert)
    return BillingAlertDispatchResult(event=event, dispatched_destinations=dispatched)


def delete_alert_and_destinations(alert: BillingAlertConfiguration) -> None:
    with transaction.atomic():
        soft_delete_all_alert_destinations(
            team_id=alert.execution_team_id,
            alert_id=str(alert.id),
            allowed_event_ids=BILLING_ALERT_EVENT_IDS,
        )
        alert.delete()


def destinations_for_alerts(alerts: list[BillingAlertConfiguration]) -> dict[str, list[dict[str, Any]]]:
    alert_ids = {str(alert.id) for alert in alerts}
    team_ids = {alert.execution_team_id for alert in alerts}
    destination_ids_by_alert_and_type: dict[str, dict[str, list[UUID]]] = {alert_id: {} for alert_id in alert_ids}

    if not alert_ids or not team_ids:
        return {}

    hog_functions = HogFunction.objects.filter(
        team_id__in=team_ids,
        deleted=False,
        template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
    ).values_list("id", "template_id", "filters")

    for hog_function_id, template_id, filters in hog_functions:
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
            if alert_id in destination_ids_by_alert_and_type:
                destination_ids_by_alert_and_type[alert_id].setdefault(destination_type.value, []).append(
                    hog_function_id
                )
            break

    return {
        alert_id: [
            {"type": destination_type, "hog_function_ids": sorted(hog_function_ids, key=str)}
            for destination_type, hog_function_ids in sorted(destinations.items())
        ]
        for alert_id, destinations in destination_ids_by_alert_and_type.items()
    }


def destination_types_for_alerts(alerts: list[BillingAlertConfiguration]) -> dict[str, list[str]]:
    return {
        alert_id: [destination["type"] for destination in destinations]
        for alert_id, destinations in destinations_for_alerts(alerts).items()
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
    existing_types = destination_types_for_alerts([alert]).get(str(alert.id), [])
    if destination_data["type"].value in existing_types:
        raise DRFValidationError({"type": f"A {destination_data['type'].label} destination already exists."})
    configs = [
        build_alert_destination_config(
            team=alert.team,
            spec=EVENT_KIND_CONFIG[kind],
            alert_id=str(alert.id),
            alert_name=alert.name,
            data=destination_data,
            slack_context_elements=BILLING_ALERT_SLACK_CONTEXT_ELEMENTS,
        )
        for kind in EVENT_KINDS
    ]
    hog_functions = create_alert_destination_hog_functions(configs, request=request)
    return [hog_function.id for hog_function in hog_functions]


def delete_destination(alert: BillingAlertConfiguration, hog_function_ids: list[UUID]) -> None:
    try:
        soft_delete_alert_destinations(
            team_id=alert.execution_team_id,
            alert_id=str(alert.id),
            allowed_event_ids=BILLING_ALERT_EVENT_IDS,
            hog_function_ids=hog_function_ids,
        )
    except DRFValidationError as error:
        raise BillingAlertDestinationOwnershipError from error


__all__ = [
    "BILLING_ALERT_EVENT_IDS",
    "BILLING_DESTINATION_TYPES",
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
    "destinations_for_alerts",
    "destination_types_for_alerts",
    "evaluate_and_dispatch_alert",
    "execution_team_for_organization",
    "slack_integration_belongs_to_team",
    "visible_events_for_alert",
]

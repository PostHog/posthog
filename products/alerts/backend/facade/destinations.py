"""Facade for alert notification destinations.

The only door other products use to configure, read, and dispatch alert destinations.
Everything here takes and returns contracts and ids; HogFunction rows, querysets and DRF
objects stay inside the product.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from posthog.cdp.internal_events import LEGACY_INSIGHT_ALERT_EVENT
from posthog.kafka_client.client import ProduceResult
from posthog.models.team import Team
from posthog.models.user import User

from ..logic import destination_configs, destinations, insight_alert_destinations
from .contracts import (
    ActiveAlertDestination,
    AlertDelivery,
    AlertDestinationConfig,
    AlertDestinationData,
    AlertDestinationGroup,
    DestinationType,
    EventKindSpec,
    OwnedAlertDestination,
)

ALERT_NOTIFICATION_FLUSH_TIMEOUT_SECONDS: Final = destinations.ALERT_NOTIFICATION_FLUSH_TIMEOUT_SECONDS

# The event an insight alert check emits, named legacy where it is defined because it predates the
# managed-alert event boundary.
INSIGHT_ALERT_EVENT_IDS: Final[tuple[str, ...]] = (LEGACY_INSIGHT_ALERT_EVENT,)

# Slack only, because `alert:write` is grantable to a sandboxed agent. A connected workspace is a
# destination an admin chose, while every other transport takes a URL the caller supplies.
INSIGHT_ALERT_DESTINATION_TYPES: Final[tuple[DestinationType, ...]] = (DestinationType.SLACK,)

# Each destination is another message every time the alert fires, so a caller in a loop is capped.
MAX_DESTINATIONS_PER_ALERT: Final = 5

# One destination is one HogFunction, so this only stops a malformed request becoming a huge query.
MAX_DESTINATION_IDS_PER_DELETE_REQUEST: Final = 100


def destination_template_id(destination_type: DestinationType) -> str:
    """The HogFunction template one destination type is stored as."""
    return destination_configs.DESTINATION_SPECS[destination_type].template_id


def redact_destination_data(data: AlertDestinationData) -> AlertDestinationData:
    """Drop the parts of a destination's configuration that are a credential."""
    return destination_configs.DESTINATION_SPECS[DestinationType(data["type"])].redact(data)


def redact_urls_in_name(name: str) -> str:
    """Replace every URL in a free-text name with its host."""
    return destinations.redact_urls_in_name(name)


def validate_destination_data(
    data: AlertDestinationData, *, allowed_destination_types: Sequence[DestinationType]
) -> None:
    """Raise `AlertDestinationValidationError` when the payload cannot become a destination."""
    destination_configs.validate_destination_data(data, allowed_destination_types=allowed_destination_types)


def build_alert_destination_config(
    *,
    team_id: int,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    data: AlertDestinationData,
    slack_context_elements: tuple[str, ...],
) -> AlertDestinationConfig:
    return destination_configs.build_alert_destination_config(
        team_id=team_id,
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        data=data,
        slack_context_elements=slack_context_elements,
    )


def build_insight_alert_slack_config(
    *, team_id: int, alert_id: str, alert_name: str | None, data: AlertDestinationData
) -> AlertDestinationConfig:
    return insight_alert_destinations.build_insight_alert_slack_config(
        team_id=team_id, alert_id=alert_id, alert_name=alert_name, data=data
    )


def create_alert_destination_hog_functions(
    configs: list[AlertDestinationConfig],
    *,
    team: Team,
    created_by: User,
    alert_id: str,
    allowed_event_ids: Collection[str],
) -> tuple[UUID, ...]:
    """Persist the configs as destinations for one alert and return the new ids."""
    return destinations.create_alert_destination_hog_functions(
        configs, team=team, created_by=created_by, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def soft_delete_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str], hog_function_ids: list[UUID]
) -> None:
    destinations.soft_delete_alert_destinations(
        team_id=team_id,
        alert_id=alert_id,
        allowed_event_ids=allowed_event_ids,
        hog_function_ids=hog_function_ids,
    )


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> int:
    return destinations.soft_delete_all_alert_destinations(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def soft_delete_alert_destinations_for_alerts(
    *, team_id: int, alert_ids: Collection[str], allowed_event_ids: Collection[str]
) -> int:
    return destinations.soft_delete_alert_destinations_for_alerts(
        team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids
    )


def list_alert_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    """The destinations configured for one alert, one entry per destination a person added."""
    return destinations.list_alert_destination_groups(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def list_owned_alert_destinations(
    *,
    team_id: int,
    alert_ids: Collection[str],
    allowed_event_ids: Collection[str],
    template_ids: Collection[str] | None = None,
    enabled: bool | None = None,
) -> tuple[OwnedAlertDestination, ...]:
    """Alert-owned destination rows, without their stored inputs."""
    return destinations.list_owned_alert_destinations(
        team_id=team_id,
        alert_ids=alert_ids,
        allowed_event_ids=allowed_event_ids,
        template_ids=template_ids,
        enabled=enabled,
    )


def count_active_alert_destinations(*, team_id: int, alert_id: str, allowed_event_ids: Collection[str]) -> int:
    return destinations.count_active_alert_destinations(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def list_active_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[ActiveAlertDestination]:
    return destinations.list_active_alert_destinations(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def serialize_deliveries(deliveries: Sequence[AlertDelivery]) -> list[dict[str, Any]]:
    """Delivery receipts in the shape an alert check stores them in."""
    return destinations.serialize_deliveries(deliveries)


def produce_alert_internal_event(
    *,
    team_id: int,
    event_name: str,
    properties: dict[str, Any],
    timestamp: datetime | None = None,
    uuid: str | None = None,
) -> ProduceResult | None:
    """Enqueue the internal event that makes the destinations for an alert fire."""
    return destinations.produce_alert_internal_event(
        team_id=team_id, event_name=event_name, properties=properties, timestamp=timestamp, uuid=uuid
    )


def flush_alert_internal_events(timeout_seconds: float) -> None:
    destinations.flush_alert_internal_events(timeout_seconds)


def alert_internal_event_delivered(
    produce_result: ProduceResult, *, team_id: int, alert_id: str, event_name: str
) -> bool:
    """Whether the broker acknowledged the event. This does not confirm the destination ran."""
    return destinations.alert_internal_event_delivered(
        produce_result, team_id=team_id, alert_id=alert_id, event_name=event_name
    )

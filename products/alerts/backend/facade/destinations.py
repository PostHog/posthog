"""Facade for alert notification destinations.

The only door other products use to configure, read, and dispatch alert destinations.
Everything here takes and returns contracts and ids; HogFunction rows, querysets and DRF
objects stay inside the product.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from posthog.kafka_client.client import ProduceResult

from products.alerts_platform.backend.facade.contracts import (
    ActiveAlertDestination,
    AlertDelivery,
    AlertDestinationConfig,
    AlertDestinationData,
    AlertDestinationGroup,
    DeliveryPath,
    DestinationType,
    EventKindSpec,
    OwnedAlertDestination,
    SourceKind,
)

from ..logic import (
    delivery_destinations,
    delivery_path,
    destination_bucket_report,
    destination_configs,
    destination_eligibility,
    destinations,
    insight_alert_destinations,
    insight_alert_message,
)
from .contracts import (
    AlertInternalEvent,
    DeliveryPathChoice,
    DestinationBucket,
    DestinationEligibility,
    DestinationHoldBack,
)

ALERT_NOTIFICATION_FLUSH_TIMEOUT_SECONDS: Final = 10.0

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
    return destinations.redact_urls_in_name(name)


def validate_destination_data(
    data: AlertDestinationData, *, allowed_destination_types: Sequence[DestinationType]
) -> None:
    """Raise `AlertDestinationValidationError` when the payload cannot become a destination."""
    destination_configs.validate_destination_data(data, allowed_destination_types=allowed_destination_types)


def destination_handles_event_kind(destination_type: DestinationType, spec: EventKindSpec) -> bool:
    """Whether a destination type has something to send for one event kind.

    An incident manager such as PagerDuty follows only the kinds that trigger or resolve an
    incident, so a product filters its event kinds with this before it builds configs.
    """
    return destination_configs.destination_handles_event_kind(destination_type, spec)


def build_alert_destination_config(
    *,
    spec: EventKindSpec,
    alert_id: str,
    alert_name: str,
    data: AlertDestinationData,
    slack_context_elements: tuple[str, ...],
) -> AlertDestinationConfig:
    return destination_configs.build_alert_destination_config(
        spec=spec,
        alert_id=alert_id,
        alert_name=alert_name,
        data=data,
        slack_context_elements=slack_context_elements,
    )


def build_insight_alert_slack_config(
    *, alert_id: str, alert_name: str | None, data: AlertDestinationData
) -> AlertDestinationConfig:
    return insight_alert_destinations.build_insight_alert_slack_config(
        alert_id=alert_id, alert_name=alert_name, data=data
    )


def insight_alert_slack_properties(
    *,
    breaches: list[str],
    metric_name: str,
    is_anomaly: bool = False,
    tags: list[str] | None = None,
    breach_details: list[dict[str, str]] | None = None,
    affected_dates: list[str] | None = None,
    affected_interval: str | None = None,
    project_timezone: str = "UTC",
    metric_description: str | None = None,
    next_step: str | None = None,
    summary: str | None,
    verdict: str | None,
    investigation_status: str | None,
    detected_at: str,
    allowed_root: str,
) -> dict[str, Any]:
    return insight_alert_message.insight_alert_slack_properties(
        breaches=breaches,
        metric_name=metric_name,
        is_anomaly=is_anomaly,
        tags=tags,
        breach_details=breach_details,
        affected_dates=affected_dates,
        affected_interval=affected_interval,
        project_timezone=project_timezone,
        metric_description=metric_description,
        next_step=next_step,
        summary=summary,
        verdict=verdict,
        investigation_status=investigation_status,
        detected_at=detected_at,
        allowed_root=allowed_root,
    )


def create_alert_destination_hog_functions(
    configs: list[AlertDestinationConfig],
    *,
    team_id: int,
    created_by_id: int,
    alert_id: str,
    allowed_event_ids: Collection[str],
) -> tuple[UUID, ...]:
    """Persist the configs as destinations for one alert and return the new ids."""
    return destinations.create_alert_destination_hog_functions(
        configs, team_id=team_id, created_by_id=created_by_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
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


def owned_alert_destination_ids(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str], hog_function_ids: Collection[UUID]
) -> frozenset[UUID]:
    return destinations.owned_alert_destination_ids(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids, hog_function_ids=hog_function_ids
    )


def list_owned_alert_destinations(
    *,
    team_id: int,
    alert_ids: Collection[str],
    allowed_event_ids: Collection[str],
    template_ids: Collection[str],
    enabled: bool,
) -> tuple[OwnedAlertDestination, ...]:
    return destinations.list_owned_alert_destinations(
        team_id=team_id,
        alert_ids=alert_ids,
        allowed_event_ids=allowed_event_ids,
        template_ids=template_ids,
        enabled=enabled,
    )


def configured_destination_template_ids(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> frozenset[str]:
    return destinations.configured_destination_template_ids(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
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
    return [asdict(delivery) for delivery in deliveries]


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


def emit_alert_internal_events(
    *, team_id: int, alert_id: str, events: Sequence[AlertInternalEvent], flush_timeout_seconds: float
) -> None:
    """Enqueue the events and wait for the broker. Raises `AlertInternalEventsNotDelivered` when it took not all of them.

    Each event's `uuid` is what lets a receiver drop the copy a retry emits.
    """
    destinations.emit_alert_internal_events(
        team_id=team_id, alert_id=alert_id, events=events, flush_timeout_seconds=flush_timeout_seconds
    )


def list_delivery_destination_groups(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    """Everything the shared platform delivers one alert's events to, including subscriber email and
    in-app notifications."""
    return delivery_destinations.list_delivery_destination_groups(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def classify_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> tuple[DestinationEligibility, ...]:
    """Every destination function of one alert, with what native delivery cannot carry for each."""
    return destination_eligibility.classify_alert_destinations(
        team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )


def customized_alert_destination_ids(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> frozenset[UUID]:
    """The destination functions of one alert that send something other than the stock message.

    A refused address is not an edit: such a function still sends the stock message.
    """
    return frozenset(
        eligibility.hog_function_id
        for eligibility in destination_eligibility.classify_alert_destinations(
            team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
        )
        if set(eligibility.hold_backs) - {DestinationHoldBack.REFUSED_ADDRESS}
    )


def unrevised_hold_backs(
    config: AlertDestinationConfig, *, allowed_event_ids: Collection[str]
) -> tuple[DestinationHoldBack, ...]:
    """What a destination built from this config holds back when it has no revision to compare with.

    Empty means the source lists every message the builder wrote as one of its defaults.
    """
    return destination_eligibility.unrevised_hold_backs(
        config.payload["template_id"], config.payload["inputs"], allowed_event_ids
    )


def unbound_alert_destinations(
    *, team_id: int, allowed_event_ids: Collection[str], include_disabled: bool = False
) -> tuple[UUID, ...]:
    """Functions that take a source's alert events without being bound to one alert, enabled ones only by default."""
    return destination_eligibility.unbound_alert_destinations(
        team_id=team_id, allowed_event_ids=allowed_event_ids, include_disabled=include_disabled
    )


def bucket_for(eligibility: DestinationEligibility) -> DestinationBucket:
    """The most restrictive bucket among a destination's hold-backs. No hold-back means stock."""
    return destination_eligibility.bucket_for(eligibility)


def bucket_report_lines(team_alerts: Iterable[tuple[int, str]], *, allowed_event_ids: Collection[str]) -> Iterator[str]:
    """One line per destination of the given (team id, alert id) pairs, then the count per bucket and per reason."""
    return destination_bucket_report.bucket_report_lines(team_alerts, allowed_event_ids=allowed_event_ids)


def team_delivery_paths(
    *, source: SourceKind, team_id: int, alert_ids: Sequence[str], allowed_event_ids: Collection[str]
) -> dict[str, DeliveryPathChoice]:
    """Whether native delivery may send each alert's destinations now, and why not when it may not."""
    return delivery_path.team_delivery_paths(
        source=source, team_id=team_id, alert_ids=alert_ids, allowed_event_ids=allowed_event_ids
    )


def choose_delivery_path(
    *, source: SourceKind, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> DeliveryPath:
    """The platform's delivery path chooser, which `products.alerts` registers when Django starts."""
    return delivery_path.delivery_path(
        source=source, team_id=team_id, alert_id=alert_id, allowed_event_ids=allowed_event_ids
    )

"""Shared persistence and dispatch mechanics for alert notification destinations.

The pure config builders live in common/alerting/destinations.py; this module owns
the Django/CDP side every alerting product otherwise duplicates: creating the
HogFunctions through HogFunctionSerializer (so template lookup and bytecode
compilation run), ownership-checked soft deletion, destination-type discovery for
list views, and producing the internal event that CDP destinations consume.

CDP exposes no facade today, so this is deliberately the one place that hand-drives
HogFunctionSerializer for alerts — when a CDP facade lands, only this module moves.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event

from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

from common.alerting.destinations import ALERT_ID_PROPERTY, DESTINATION_TYPE_BY_TEMPLATE_ID


class AlertDestinationOwnershipError(Exception):
    """Raised when deleting destinations that do not all belong to an alert."""


def create_alert_destination_hog_functions(configs: list[dict[str, Any]], *, request: Any) -> list[HogFunction]:
    """Create one HogFunction per config, atomically. Each config carries its `team`."""
    created: list[HogFunction] = []
    with transaction.atomic():
        for config in configs:
            config = dict(config)
            team = config.pop("team")
            serializer = HogFunctionSerializer(
                data=config,
                context={"request": request, "get_team": lambda team=team: team, "is_create": True},
            )
            serializer.is_valid(raise_exception=True)
            created.append(serializer.save(team=team))
    return created


def soft_delete_alert_destinations(
    *,
    team_id: int,
    alert_id: str,
    hog_function_ids: list[UUID],
) -> None:
    """Soft-delete a destination's HogFunction group, verifying every ID belongs to the alert.

    The filtered UPDATE is the ownership check: touching fewer rows than requested
    means something in the list doesn't belong to this alert — roll back.
    """
    unique_ids = set(hog_function_ids)
    with transaction.atomic():
        updated = HogFunction.objects.filter(
            team_id=team_id,
            id__in=unique_ids,
            filters__properties__contains=[{"key": ALERT_ID_PROPERTY, "value": alert_id}],
        ).update(deleted=True, enabled=False)
        if updated != len(unique_ids):
            raise AlertDestinationOwnershipError


def soft_delete_all_alert_destinations(*, team_id: int, alert_id: str) -> int:
    """Soft-delete every destination HogFunction linked to an alert (alert deletion path)."""
    return HogFunction.objects.filter(
        team_id=team_id,
        deleted=False,
        template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
        filters__properties__contains=[{"key": ALERT_ID_PROPERTY, "value": alert_id}],
    ).update(deleted=True, enabled=False)


def find_alert_destination_hog_functions(*, team_id: int, alert_id: str, event_id: str) -> list[HogFunction]:
    """The dispatch-side half of the linkage contract in common/alerting/destinations.py."""
    return list(
        HogFunction.objects.filter(
            team_id=team_id,
            deleted=False,
            template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
            filters__events__contains=[{"id": event_id, "type": "events"}],
            filters__properties__contains=[{"key": ALERT_ID_PROPERTY, "value": alert_id}],
        ).only("id", "template_id")
    )


def destination_types_for_alerts(*, team_ids: Iterable[int], alert_ids: Iterable[str]) -> dict[str, list[str]]:
    """Map alert_id -> sorted destination types, for list views (no FK exists — read filters JSON)."""
    alert_id_set = set(alert_ids)
    team_id_set = set(team_ids)
    destination_types_by_alert_id: dict[str, set[str]] = {alert_id: set() for alert_id in alert_id_set}

    if not alert_id_set or not team_id_set:
        return {}

    hog_functions = HogFunction.objects.filter(
        team_id__in=team_id_set,
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
            if not isinstance(property_filter, dict) or property_filter.get("key") != ALERT_ID_PROPERTY:
                continue
            alert_id = str(property_filter.get("value"))
            if alert_id in destination_types_by_alert_id:
                destination_types_by_alert_id[alert_id].add(destination_type)

    return {
        alert_id: sorted(destination_types) for alert_id, destination_types in destination_types_by_alert_id.items()
    }


def produce_alert_internal_event(
    *,
    team_id: int,
    event_name: str,
    properties: dict[str, Any],
    timestamp: datetime | None = None,
    uuid: str | None = None,
) -> None:
    """Produce the internal event CDP destinations consume. Callers own error handling."""
    produce_internal_event(
        team_id=team_id,
        event=InternalEventEvent(
            event=event_name,
            distinct_id=f"team_{team_id}",
            properties=properties,
            timestamp=timestamp.isoformat() if timestamp else None,
            uuid=uuid,
        ),
    )

"""The write path for team-wide receivers and the routes that pick which alerts they hear.

Delivery reads these rows in `alert_routes.routed_receivers`. Everything it would trip on is
refused here, so one bad row cannot fail the routed sends of every alert on the team.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count

from products.alerts_platform.backend.facade.contracts import (
    ROUTABLE_DESTINATION_TYPES,
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    AlertReceiverEdit,
    AlertRouteEdit,
    RouteMatcher,
    StoredAlertReceiver,
    StoredAlertRoute,
    UnknownAlertRouting,
)
from products.alerts_platform.backend.logic.alert_destinations import validate_destination_data, validate_event_kinds
from products.alerts_platform.backend.logic.rule_metadata import InvalidRuleMetadata, validate_labels
from products.alerts_platform.backend.models import AlertReceiver, AlertRoute

DEFAULT_ROUTE_EVENT_KINDS: Final = (
    AlertEventKind.FIRING,
    AlertEventKind.RESOLVED,
    AlertEventKind.ERRORED,
    AlertEventKind.BROKEN,
)
_EQUALS: Final = "="


def list_receivers(*, team_id: int) -> tuple[StoredAlertReceiver, ...]:
    rows = AlertReceiver.objects.for_team(team_id).annotate(route_count=Count("routes")).order_by("name", "id")
    return tuple(_stored_receiver(row, row.route_count) for row in rows)


def create_receiver(*, team_id: int, edit: AlertReceiverEdit) -> StoredAlertReceiver:
    if edit.name is None or edit.data is None:
        raise AlertDestinationValidationError("A receiver needs a name and a destination.")
    name = _valid_name(edit.name)
    _validate_receiver_data(edit.data)
    try:
        with transaction.atomic():
            row = AlertReceiver.objects.for_team(team_id).create(
                team_id=team_id,
                name=name,
                type=edit.data["type"],
                config=dict(edit.data),
                enabled=True if edit.enabled is None else edit.enabled,
            )
    except IntegrityError as error:
        raise _duplicate_name(name) from error
    return _stored_receiver(row, 0)


def update_receiver(*, team_id: int, receiver_id: UUID, edit: AlertReceiverEdit) -> StoredAlertReceiver:
    with transaction.atomic():
        row = AlertReceiver.objects.for_team(team_id).select_for_update().filter(id=receiver_id).first()
        if row is None:
            raise UnknownAlertRouting()
        if edit.name is not None:
            row.name = _valid_name(edit.name)
        if edit.data is not None:
            _validate_receiver_data(edit.data)
            row.type = edit.data["type"]
            row.config = dict(edit.data)
        if edit.enabled is not None:
            # nosemgrep: platform-alert-state-direct-mutation (a routing row's own switch, not an alert's lifecycle)
            row.enabled = edit.enabled
        try:
            with transaction.atomic():
                row.save()
        except IntegrityError as error:
            raise _duplicate_name(row.name) from error
    return _stored_receiver(row, AlertRoute.objects.for_team(team_id).filter(receiver_id=row.id).count())


def delete_receiver(*, team_id: int, receiver_id: UUID) -> None:
    """Deletes the receiver and every route that sends to it."""
    deleted, _ = AlertReceiver.objects.for_team(team_id).filter(id=receiver_id).delete()
    if not deleted:
        raise UnknownAlertRouting()


def list_routes(*, team_id: int) -> tuple[StoredAlertRoute, ...]:
    rows = AlertRoute.objects.for_team(team_id).order_by("position", "created_at", "id")
    return tuple(_stored_route(row) for row in rows)


def create_route(*, team_id: int, edit: AlertRouteEdit) -> StoredAlertRoute:
    if edit.receiver_id is None:
        raise AlertDestinationValidationError("Choose a receiver for this route.", field="receiver_id")
    _check_receiver(team_id, edit.receiver_id)
    matchers = edit.matchers or ()
    _validate_matchers(matchers)
    event_kinds = edit.event_kinds or DEFAULT_ROUTE_EVENT_KINDS
    validate_event_kinds(event_kinds)
    try:
        with transaction.atomic():
            row = AlertRoute.objects.for_team(team_id).create(
                team_id=team_id,
                receiver_id=edit.receiver_id,
                matchers=_stored_matchers(matchers),
                event_kinds=[kind.value for kind in event_kinds],
                enabled=True if edit.enabled is None else edit.enabled,
            )
    except IntegrityError as error:
        # The receiver was deleted after the check above. Postgres checks the foreign key at commit,
        # which is the exit of this block.
        raise _unknown_receiver() from error
    return _stored_route(row)


def update_route(*, team_id: int, route_id: UUID, edit: AlertRouteEdit) -> StoredAlertRoute:
    # Postgres checks the receiver foreign key at commit, so a receiver deleted after the check below
    # fails when this block exits.
    try:
        with transaction.atomic():
            row = AlertRoute.objects.for_team(team_id).select_for_update().filter(id=route_id).first()
            if row is None:
                raise UnknownAlertRouting()
            if edit.receiver_id is not None:
                _check_receiver(team_id, edit.receiver_id)
                row.receiver_id = edit.receiver_id
            if edit.matchers is not None:
                _validate_matchers(edit.matchers)
                row.matchers = _stored_matchers(edit.matchers)
            if edit.event_kinds is not None:
                validate_event_kinds(edit.event_kinds)
                row.event_kinds = [kind.value for kind in edit.event_kinds]
            if edit.enabled is not None:
                # nosemgrep: platform-alert-state-direct-mutation (a routing row's own switch, not an alert's lifecycle)
                row.enabled = edit.enabled
            row.save()
    except IntegrityError as error:
        raise _unknown_receiver() from error
    return _stored_route(row)


def delete_route(*, team_id: int, route_id: UUID) -> None:
    deleted, _ = AlertRoute.objects.for_team(team_id).filter(id=route_id).delete()
    if not deleted:
        raise UnknownAlertRouting()


def _valid_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise AlertDestinationValidationError("Enter a name for this receiver.", field="name")
    return stripped


def _duplicate_name(name: str) -> AlertDestinationValidationError:
    return AlertDestinationValidationError(f"A receiver named {name!r} already exists.", field="name")


def _validate_receiver_data(data: AlertDestinationData) -> None:
    if data.get("type") not in ROUTABLE_DESTINATION_TYPES:
        raise AlertDestinationValidationError("Routes cannot send to this destination type.", field="type")
    validate_destination_data(data)


def _check_receiver(team_id: int, receiver_id: UUID) -> None:
    # Delivery loads receivers by team, so a route to another team's receiver would never send.
    if not AlertReceiver.objects.for_team(team_id).filter(id=receiver_id).exists():
        raise _unknown_receiver()


def _unknown_receiver() -> AlertDestinationValidationError:
    return AlertDestinationValidationError("Choose a receiver in this project.", field="receiver_id")


def _validate_matchers(matchers: tuple[RouteMatcher, ...]) -> None:
    labels: dict[str, str] = {}
    for matcher in matchers:
        if matcher.label in labels:
            raise AlertDestinationValidationError(
                f"Label `{matcher.label}` is matched twice. A route can check each label once.", field="matchers"
            )
        labels[matcher.label] = matcher.value
    # The rules an alert's own labels follow, so a route never matches on a label no alert can have.
    try:
        validate_labels(labels)
    except InvalidRuleMetadata as error:
        raise AlertDestinationValidationError(str(error), field="matchers") from error


def _stored_matchers(matchers: tuple[RouteMatcher, ...]) -> list[dict[str, str]]:
    return [{"label": matcher.label, "op": _EQUALS, "value": matcher.value} for matcher in matchers]


def _stored_receiver(row: AlertReceiver, route_count: int) -> StoredAlertReceiver:
    return StoredAlertReceiver(
        id=row.id,
        name=row.name,
        data=cast(AlertDestinationData, row.config),
        enabled=row.enabled,
        route_count=route_count,
    )


def _stored_route(row: AlertRoute) -> StoredAlertRoute:
    return StoredAlertRoute(
        id=row.id,
        receiver_id=row.receiver_id,
        matchers=tuple(_matcher(matcher) for matcher in cast(list[Mapping[str, str]], row.matchers)),
        event_kinds=tuple(AlertEventKind(kind) for kind in row.event_kinds),
        enabled=row.enabled,
    )


def _matcher(stored: Mapping[str, str]) -> RouteMatcher:
    return RouteMatcher(label=stored["label"], value=stored["value"])

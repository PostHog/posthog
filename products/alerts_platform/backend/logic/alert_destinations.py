"""An alert's `AlertDestination` rows. Delivery sends to them beside any HogFunctions the alert has.

The one write path for `AlertDestination`. Each source's alert page and the central page call it
through the facade, so a destination is valid or refused the same way wherever it is edited.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import Final, cast
from urllib.parse import urlsplit
from uuid import UUID

from django.db import models, transaction

from products.alerts_platform.backend.delivery.addresses import refused_destination
from products.alerts_platform.backend.delivery.destinations import list_alert_destination_groups
from products.alerts_platform.backend.facade.contracts import (
    DESTINATION_EVENT_KINDS,
    AlertDestinationData,
    AlertDestinationGroup,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    SourceDestination,
    StoredAlertDestination,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import AlertDestination, PlatformAlertConfiguration

# The destination types that open and close incidents rather than post messages.
INCIDENT_DESTINATION_TYPES: Final = frozenset({DestinationType.PAGERDUTY})

_REQUIRED_FIELDS: Final[dict[DestinationType, tuple[str, ...]]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id"),
    DestinationType.WEBHOOK: ("webhook_url",),
    DestinationType.TEAMS: ("webhook_url",),
    DestinationType.DISCORD: ("webhook_url",),
    DestinationType.PAGERDUTY: ("pagerduty_routing_key",),
    DestinationType.EMAIL: ("email_addresses",),
    DestinationType.IN_APP: ("in_app_user_ids",),
}


def _is_text(value: object) -> bool:
    return isinstance(value, str)


def _is_id(value: object) -> bool:
    # A bool is an int in Python, but never a valid id.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_list_of(check: Callable[[object], bool]) -> Callable[[object], bool]:
    return lambda value: isinstance(value, list) and all(check(item) for item in value)


_FIELD_CHECKS: Final[dict[str, Callable[[object], bool]]] = {
    "slack_workspace_id": _is_id,
    "slack_channel_id": _is_text,
    "webhook_url": _is_text,
    "pagerduty_routing_key": _is_text,
    "email_addresses": _is_list_of(_is_text),
    "email_user_ids": _is_list_of(_is_id),
    "in_app_user_ids": _is_list_of(_is_id),
}

# A label a person sees. Two destinations that differ only here send to the same place.
_DISPLAY_ONLY_FIELDS: Final = frozenset({"slack_channel_name"})


def create_alert_destinations(
    *,
    team_id: int,
    configuration_id: UUID,
    destinations: Sequence[NewAlertDestination],
    hog_function_event_ids: Collection[str] = (),
) -> tuple[StoredAlertDestination, ...]:
    """Adds the destinations to one configuration, all or none.

    `hog_function_event_ids` are the events the alert's HogFunctions listen on. With them, a destination
    that sends where one of those HogFunction groups already sends is refused too, unless it copies that group.
    """
    for destination in destinations:
        _validate(destination)
    with transaction.atomic():
        # Locked, so two adds of the same destination cannot both pass the duplicate check.
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id).select_for_update().get(id=configuration_id)
        )
        _refuse_duplicates(team_id, configuration, destinations, hog_function_event_ids)
        rows = [
            AlertDestination.objects.for_team(team_id).create(
                team_id=team_id,
                configuration=configuration,
                type=destination.data["type"],
                config=dict(destination.data),
                event_kinds=[kind.value for kind in destination.event_kinds],
                enabled=destination.enabled,
                legacy_hog_function_ids=list(destination.legacy_hog_function_ids),
            )
            for destination in destinations
        ]
    return tuple(_stored(row) for row in rows)


def list_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    return tuple(
        _stored(row)
        for row in AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id)
        .order_by("created_at", "id")
    )


def destination_types_by_configuration(
    *, team_id: int, configuration_ids: Collection[UUID]
) -> dict[UUID, tuple[str, ...]]:
    """The types of each named configuration's enabled destinations, in one query. A configuration with
    none is left out."""
    types: dict[UUID, list[str]] = {}
    for configuration_id, destination_type in (
        AlertDestination.objects.for_team(team_id)
        .filter(configuration_id__in=configuration_ids, enabled=True)
        .order_by("created_at", "id")
        .values_list("configuration_id", "type")
    ):
        if destination_type not in types.setdefault(configuration_id, []):
            types[configuration_id].append(destination_type)
    return {configuration_id: tuple(found) for configuration_id, found in types.items()}


def delete_alert_destinations(*, team_id: int, configuration_id: UUID, destination_ids: Collection[UUID]) -> int:
    """Deletes the named destinations of one configuration, and returns how many it deleted.

    An id of another configuration is left alone, so a caller cannot reach past the alert it checked access to.
    """
    deleted, _ = (
        AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, id__in=destination_ids)
        .delete()
    )
    return deleted


def enabled_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    """The destinations delivery sends to. A disabled one is left out before its address is decrypted."""
    return tuple(
        _stored(row)
        for row in AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, enabled=True)
        .order_by("created_at", "id")
    )


def has_incident_destination(*, team_id: int, configuration_id: UUID) -> bool:
    """Whether the alert has an enabled incident manager, so that a firing that opens or closes needs a delivery."""
    return (
        AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, type__in=INCIDENT_DESTINATION_TYPES, enabled=True)
        .exists()
    )


def hears_kind(
    *, team_id: int, configuration_id: UUID, destination_type: DestinationType, event_kind: AlertEventKind
) -> bool:
    """Whether an enabled destination of this type on the alert sends messages of this kind."""
    return (
        AlertDestination.objects.for_team(team_id)
        .filter(
            configuration_id=configuration_id,
            type=destination_type,
            enabled=True,
            event_kinds__contains=[event_kind.value],
        )
        .exists()
    )


def set_subscriber_destinations(
    *,
    team_id: int,
    public_id: UUID,
    user_ids: Collection[int],
    event_kinds: Collection[AlertEventKind],
    in_app_resource_type: str,
    in_app_resource_id: str,
) -> bool:
    """Replaces the alert's subscribers: one email and one in-app destination naming the same users,
    or none when nobody subscribes. False when the platform has no alert under this public id."""
    with transaction.atomic():
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id)
            .select_for_update()
            .filter(PlatformAlertConfiguration.with_destination_alert_ids([public_id]))
            .first()
        )
        if configuration is None:
            return False
        stale = [row.id for row in _subscriber_rows(team_id, [configuration.id])]
        AlertDestination.objects.for_team(team_id).filter(id__in=stale).delete()
        users = sorted(set(user_ids))
        if users:
            kinds = [kind.value for kind in event_kinds]
            subscribers: list[AlertDestinationData] = [
                {"type": DestinationType.EMAIL, "email_user_ids": users},
                {
                    "type": DestinationType.IN_APP,
                    "in_app_user_ids": users,
                    "in_app_resource_type": in_app_resource_type,
                    "in_app_resource_id": in_app_resource_id,
                },
            ]
            AlertDestination.objects.for_team(team_id).bulk_create(
                AlertDestination(
                    team_id=team_id,
                    configuration=configuration,
                    type=data["type"],
                    config=dict(data),
                    event_kinds=kinds,
                )
                for data in subscribers
            )
    return True


def subscriber_user_ids_by_public_id(*, team_id: int, public_ids: Collection[UUID]) -> dict[UUID, tuple[int, ...]]:
    """The users each alert's subscriber destinations name. An alert with none is left out."""
    configurations = dict(
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(PlatformAlertConfiguration.with_destination_alert_ids(public_ids))
        .values_list("id", "legacy_configuration_id")
    )
    return {
        configurations[row.configuration_id] or row.configuration_id: tuple(row.config["email_user_ids"])
        for row in _subscriber_rows(team_id, configurations)
        if row.type == DestinationType.EMAIL
    }


def remove_subscriber(*, team_ids: Collection[int], user_id: int) -> int:
    """Takes a user out of every subscriber destination of these teams' alerts, and returns how many
    alerts named them. A destination left naming nobody is deleted.

    One alert per transaction, in id order, so this never holds two alerts' locks at once.
    """
    removed = 0
    for team_id in team_ids:
        rows = (
            AlertDestination.objects.for_team(team_id)
            .filter(type__in=[DestinationType.EMAIL, DestinationType.IN_APP])
            .only("configuration_id", "type", "config")
            .iterator(chunk_size=500)
        )
        naming = sorted({row.configuration_id for row in rows if user_id in _subscriber_user_ids(row)})
        for configuration_id in naming:
            with transaction.atomic():
                PlatformAlertConfiguration.objects.for_team(team_id).select_for_update().filter(
                    id=configuration_id
                ).first()
                for row in _subscriber_rows(team_id, [configuration_id]):
                    remaining = [named for named in _subscriber_user_ids(row) if named != user_id]
                    if not remaining:
                        row.delete()
                        continue
                    key = "email_user_ids" if row.type == DestinationType.EMAIL else "in_app_user_ids"
                    row.config = {**row.config, key: remaining}
                    row.save(update_fields=["config", "updated_at"])
            removed += 1
    return removed


def _subscriber_user_ids(row: AlertDestination) -> list[int]:
    if row.type == DestinationType.EMAIL:
        return list(row.config.get("email_user_ids", []))
    return list(row.config.get("in_app_user_ids", []))


def _subscriber_rows(team_id: int, configuration_ids: Collection[UUID]) -> list[AlertDestination]:
    """Destinations that name users who subscribed, rather than a channel or addresses a person typed.

    Told apart in Python, because the config is encrypted and the database cannot read its keys.
    """
    rows = AlertDestination.objects.for_team(team_id).filter(
        configuration_id__in=list(configuration_ids), type__in=[DestinationType.EMAIL, DestinationType.IN_APP]
    )
    return [row for row in rows if _names_subscribers(row)]


def _names_subscribers(row: AlertDestination) -> bool:
    return row.type == DestinationType.IN_APP or (row.type == DestinationType.EMAIL and "email_user_ids" in row.config)


def _refuse_duplicates(
    team_id: int,
    configuration: PlatformAlertConfiguration,
    destinations: Sequence[NewAlertDestination],
    hog_function_event_ids: Collection[str],
) -> None:
    """A second destination with the same address would send every message twice."""
    seen = [
        _receiver(stored.data) for stored in list_alert_destinations(team_id=team_id, configuration_id=configuration.id)
    ]
    groups = (
        _hog_function_groups(team_id, configuration.destination_alert_id, hog_function_event_ids)
        if hog_function_event_ids
        else []
    )
    for destination in destinations:
        receiver = _receiver(destination.data)
        copied = set(destination.legacy_hog_function_ids)
        if receiver in seen or any(
            _receiver(group.data) == receiver and not copied.issuperset(group.hog_function_ids) for group in groups
        ):
            raise AlertDestinationValidationError("This alert already sends to this destination.", field="config")
        seen.append(receiver)


def record_source_destination(
    *,
    team_id: int,
    public_id: UUID,
    data: AlertDestinationData,
    event_kinds: Collection[AlertEventKind],
    hog_function_ids: Collection[UUID],
    hog_function_event_ids: Collection[str],
) -> StoredAlertDestination | None:
    """Adds the row for a destination its source has just written as `hog_function_ids`, so the
    destination outlives them. None when the platform has no alert under `public_id`, or when it keeps
    the alert's destinations itself: delivery then sends every row and emits to every HogFunction, so a
    row beside these HogFunctions would send each message twice."""
    configuration_id = (
        _configurations_by_public_id(team_id, public_id)
        .filter(destinations_owner=PlatformAlertOwner.SOURCE)
        .values_list("id", flat=True)
        .first()
    )
    if configuration_id is None:
        return None
    (created,) = create_alert_destinations(
        team_id=team_id,
        configuration_id=configuration_id,
        destinations=(
            NewAlertDestination(
                data=data, event_kinds=tuple(event_kinds), legacy_hog_function_ids=tuple(hog_function_ids)
            ),
        ),
        hog_function_event_ids=hog_function_event_ids,
    )
    return created


def list_source_destinations(
    *, team_id: int, public_id: UUID, hog_function_event_ids: Collection[str]
) -> tuple[SourceDestination, ...]:
    """The destinations a person sees on the page of an alert whose source keeps HogFunctions: each
    HogFunction group, with the row that copies it, then each row whose HogFunctions are gone.
    Subscriber rows are left out, because the source shows its subscribers apart."""
    groups = _hog_function_groups(team_id, public_id, hog_function_event_ids)
    rows = [
        _stored(row)
        for row in AlertDestination.objects.for_team(team_id)
        .filter(configuration__in=_configurations_by_public_id(team_id, public_id))
        .order_by("created_at", "id")
        if not _names_subscribers(row)
    ]
    row_by_hog_function_id = {
        hog_function_id: row for row in reversed(rows) for hog_function_id in row.legacy_hog_function_ids
    }
    matched: set[UUID] = set()
    listed: list[SourceDestination] = []
    for group in groups:
        row = next((row_by_hog_function_id[i] for i in group.hog_function_ids if i in row_by_hog_function_id), None)
        if row is not None:
            matched.add(row.id)
        listed.append(
            SourceDestination(
                destination_id=row.id if row is not None else None,
                hog_function_ids=group.hog_function_ids,
                # The row keeps what the person entered, such as a Slack channel's name, which HogFunctions do not.
                data=row.data if row is not None else group.data,
                enabled=group.fully_enabled,
            )
        )
    listed.extend(
        SourceDestination(destination_id=row.id, hog_function_ids=(), data=row.data, enabled=row.enabled)
        for row in rows
        if row.id not in matched
    )
    return tuple(listed)


def delete_source_destination_rows(
    *, team_id: int, public_id: UUID, destination_ids: Collection[UUID], hog_function_ids: Collection[UUID]
) -> frozenset[UUID]:
    """Deletes the alert's rows named by id or that copy any of `hog_function_ids`, and returns the
    HogFunctions those rows copied, which the source deletes too."""
    if not destination_ids and not hog_function_ids:
        return frozenset()
    rows = AlertDestination.objects.for_team(team_id).filter(
        models.Q(id__in=list(destination_ids)) | models.Q(legacy_hog_function_ids__overlap=list(hog_function_ids)),
        configuration__in=_configurations_by_public_id(team_id, public_id),
    )
    copied = frozenset(
        hog_function_id
        for copies in rows.values_list("legacy_hog_function_ids", flat=True)
        for hog_function_id in copies
    )
    rows.delete()
    return copied


def _configurations_by_public_id(team_id: int, public_id: UUID) -> models.QuerySet[PlatformAlertConfiguration]:
    return PlatformAlertConfiguration.objects.for_team(team_id).filter(
        PlatformAlertConfiguration.with_destination_alert_ids([public_id])
    )


def _hog_function_groups(
    team_id: int, public_id: UUID, hog_function_event_ids: Collection[str]
) -> list[AlertDestinationGroup]:
    """The alert's HogFunction destinations, without the subscriber groups a source adds with none."""
    return [
        group
        for group in list_alert_destination_groups(
            team_id=team_id, alert_id=str(public_id), allowed_event_ids=hog_function_event_ids
        )
        if group.hog_function_ids
    ]


def _receiver(data: AlertDestinationData) -> dict[str, object]:
    """What decides where and how a destination sends, without the fields that only label it."""
    return {key: value for key, value in data.items() if key not in _DISPLAY_ONLY_FIELDS}


def _validate(destination: NewAlertDestination) -> None:
    validate_destination_data(destination.data)
    validate_event_kinds(destination.event_kinds)


def validate_destination_data(data: AlertDestinationData) -> None:
    """Where and how a destination sends. A team-wide receiver shares these rules with an alert's own destination."""
    destination_type = data.get("type")
    if destination_type not in DestinationType.values:
        raise AlertDestinationValidationError("This destination type is not supported.", field="type")
    required = (
        ("email_user_ids",)
        if destination_type == DestinationType.EMAIL and "email_user_ids" in data
        else _REQUIRED_FIELDS[DestinationType(destination_type)]
    )
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise AlertDestinationValidationError(f"This destination needs {', '.join(missing)}.", field="config")
    malformed = [key for key in required if not _FIELD_CHECKS[key](data.get(key))]
    if malformed:
        raise AlertDestinationValidationError(
            f"This destination has an invalid {', '.join(malformed)}.", field="config"
        )
    refusal = refused_destination(data)
    if refusal is not None:
        raise AlertDestinationValidationError(refusal, field="config")


def validate_event_kinds(event_kinds: Collection[AlertEventKind]) -> None:
    if not event_kinds:
        raise AlertDestinationValidationError("Choose at least one event to send.", field="event_kinds")
    if not set(event_kinds) <= DESTINATION_EVENT_KINDS:
        raise AlertDestinationValidationError("A destination cannot send about this event.", field="event_kinds")


def redact_destination_data(data: AlertDestinationData) -> AlertDestinationData:
    """Drop the parts of a destination's configuration that are a credential."""
    redacted = cast(AlertDestinationData, {key: value for key, value in data.items() if key != "webhook_headers"})
    if (webhook_url := data.get("webhook_url")) is not None:
        redacted["webhook_url"] = _redact_url(webhook_url)
    if (routing_key := data.get("pagerduty_routing_key")) is not None:
        # Keep the tail a person needs to tell two integration keys apart.
        redacted["pagerduty_routing_key"] = f"••••{routing_key[-4:]}"
    return redacted


def _redact_url(value: str) -> str:
    """Keep only the parts a person needs to tell two destinations apart. The path,
    query and userinfo carry the channel secret for every webhook-style provider."""
    try:
        parsed = urlsplit(value)
        scheme, hostname, port = parsed.scheme, parsed.hostname, parsed.port
    except ValueError:
        return "<redacted>"
    if not scheme or not hostname:
        return "<redacted>"
    authority = f"{hostname}:{port}" if port is not None else hostname
    return f"{scheme}://{authority}"


def _stored(row: AlertDestination) -> StoredAlertDestination:
    return StoredAlertDestination(
        id=row.id,
        configuration_id=row.configuration_id,
        data=cast(AlertDestinationData, row.config),
        event_kinds=tuple(AlertEventKind(kind) for kind in row.event_kinds),
        enabled=row.enabled,
        consecutive_failures=row.consecutive_failures,
        legacy_hog_function_ids=tuple(row.legacy_hog_function_ids),
    )

"""Customize and reset a source alert's stock destination.

A destination sends exactly once at any moment: from its `AlertDestination` row with the standard
message, or from its HogFunctions with the message someone can edit. Each move swaps one for the
other in one transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from typing import Final, cast
from uuid import UUID

from django.db import transaction

from products.alerts.backend.facade.contracts import CustomizableDestination, DestinationHoldBack, ResetDestination
from products.alerts.backend.logic.destination_configs import (
    DESTINATION_SPECS,
    SPEC_BY_TEMPLATE_ID,
    WEBHOOK_HEADERS,
    added_webhook_headers,
    input_value,
)
from products.alerts.backend.logic.destination_eligibility import classify_alert_destinations
from products.alerts.backend.logic.destinations import (
    create_alert_destination_hog_functions,
    list_alert_destination_groups,
    list_owned_alert_destinations,
    owned_alert_destinations_qs,
    soft_delete_alert_destinations,
    stored_inputs,
)
from products.alerts.backend.logic.insight_alert_destinations import with_secret_inputs
from products.alerts_platform.backend.facade.api import (
    has_firing_instance,
    link_source_destination,
    list_source_destinations,
    lock_source_configuration,
    lock_source_destination_row,
    restore_source_destination,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationConfig,
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    SourceDestination,
)
from products.cdp.backend.facade.models import HogFunction

_GONE = "This destination has changed since the page loaded. Refresh the alert and try again."

# The configs a source writes for a new destination of a type, for the event kinds it should hear.
ConfigBuilder = Callable[[AlertDestinationData, Collection[AlertEventKind]], Sequence[AlertDestinationConfig]]


def customize_source_destination(
    *,
    team_id: int,
    alert_id: UUID,
    allowed_event_ids: Collection[str],
    allowed_destination_types: Collection[DestinationType],
    destination_id: UUID | None,
    hog_function_ids: Collection[UUID],
    build_configs: ConfigBuilder,
    created_by_id: int,
) -> CustomizableDestination:
    """Gives the destination HogFunctions to edit, keeping its row and the row's id.

    A row that copies HogFunctions which still exist is skipped by delivery, so they keep sending and
    nothing new is written. A row with none gets them built by `build_configs` from its stored settings,
    for the event kinds it heard, and copies them from then on, so delivery skips it while they exist."""
    with transaction.atomic():
        lock_source_configuration(team_id=team_id, public_id=alert_id)
        listed = _listed(
            team_id=team_id,
            alert_id=alert_id,
            allowed_event_ids=allowed_event_ids,
            destination_id=destination_id,
            hog_function_ids=hog_function_ids,
        )
        destination_type = DestinationType(listed.data["type"])
        if destination_type not in allowed_destination_types:
            raise AlertDestinationValidationError("This destination's message can't be customized.", field="type")
        _refuse_incident_move_while_firing(team_id, alert_id, destination_type)
        if listed.hog_function_ids:
            return CustomizableDestination(
                hog_function_ids=listed.hog_function_ids, destination_type=destination_type, created=False
            )
        taken = (
            lock_source_destination_row(team_id=team_id, public_id=alert_id, destination_id=listed.destination_id)
            if listed.destination_id is not None
            else None
        )
        if taken is None:
            raise AlertDestinationValidationError(_GONE)
        data = cast(AlertDestinationData, {**taken.data, "type": destination_type})
        configs = [
            _kept_secret(config, data, enabled=taken.enabled) for config in build_configs(data, taken.event_kinds)
        ]
        if not configs:
            raise AlertDestinationValidationError("This destination sends no messages to customize.", field="type")
        created = create_alert_destination_hog_functions(
            configs,
            team_id=team_id,
            created_by_id=created_by_id,
            alert_id=str(alert_id),
            allowed_event_ids=allowed_event_ids,
        )
        link_source_destination(team_id=team_id, destination_id=taken.id, hog_function_ids=created)
    return CustomizableDestination(hog_function_ids=created, destination_type=destination_type, created=True)


def reset_source_destination(
    *,
    team_id: int,
    alert_id: UUID,
    allowed_event_ids: Collection[str],
    allowed_destination_types: Collection[DestinationType],
    hog_function_ids: Collection[UUID],
    row_event_kinds: Callable[[DestinationType], Collection[AlertEventKind]],
) -> ResetDestination:
    """Retires the destination's HogFunctions and makes its row send the standard message instead, under
    the same id; a destination that never had a row gets one.

    The HogFunctions are retired with a queryset update, which the receiver that deletes copying rows
    never hears, and the row stops copying them, so it outlives them either way."""
    with transaction.atomic():
        lock_source_configuration(team_id=team_id, public_id=alert_id)
        # Locked before the read, so a concurrent edit cannot change the settings the row restores.
        list(
            owned_alert_destinations_qs(team_id=team_id, alert_ids=[str(alert_id)], allowed_event_ids=allowed_event_ids)
            .select_for_update()
            .values_list("id", flat=True)
        )
        groups = list_alert_destination_groups(
            team_id=team_id, alert_id=str(alert_id), allowed_event_ids=allowed_event_ids
        )
        named = set(hog_function_ids)
        group = next((group for group in groups if set(group.hog_function_ids) == named), None)
        if not named or group is None:
            raise AlertDestinationValidationError(_GONE, field="hog_function_ids")
        destination_type = DestinationType(group.data["type"])
        if destination_type not in allowed_destination_types:
            raise AlertDestinationValidationError(
                "This destination has no standard message to go back to.", field="type"
            )
        _refuse_incident_move_while_firing(team_id, alert_id, destination_type)
        _refuse_partly_paused(team_id, alert_id, allowed_event_ids, group.hog_function_ids)
        _refuse_what_the_standard_message_cannot_send(team_id, alert_id, allowed_event_ids, group.hog_function_ids)
        data = _with_secret_headers(team_id, group.data, group.hog_function_ids)
        soft_delete_alert_destinations(
            team_id=team_id,
            alert_id=str(alert_id),
            allowed_event_ids=allowed_event_ids,
            hog_function_ids=list(group.hog_function_ids),
        )
        row = restore_source_destination(
            team_id=team_id,
            public_id=alert_id,
            data=data,
            event_kinds=row_event_kinds(destination_type),
            enabled=group.fully_enabled,
            retired_hog_function_ids=group.hog_function_ids,
            hog_function_groups=groups,
        )
    return ResetDestination(
        destination_id=row.id, destination_type=destination_type, retired_hog_function_ids=group.hog_function_ids
    )


def _listed(
    *,
    team_id: int,
    alert_id: UUID,
    allowed_event_ids: Collection[str],
    destination_id: UUID | None,
    hog_function_ids: Collection[UUID],
) -> SourceDestination:
    listed = list_source_destinations(
        team_id=team_id,
        public_id=alert_id,
        hog_function_groups=list_alert_destination_groups(
            team_id=team_id, alert_id=str(alert_id), allowed_event_ids=allowed_event_ids
        ),
    )
    named = set(hog_function_ids)
    found = next(
        (
            destination
            for destination in listed
            if (destination_id is not None and destination.destination_id == destination_id)
            or (named and set(destination.hog_function_ids) == named)
        ),
        None,
    )
    if found is None:
        raise AlertDestinationValidationError(_GONE)
    return found


def _refuse_incident_move_while_firing(team_id: int, alert_id: UUID, destination_type: DestinationType) -> None:
    """The row and the HogFunctions key an incident differently, so an incident opened by one would
    never be resolved by the other."""
    if destination_type != DestinationType.PAGERDUTY:
        return
    if has_firing_instance(team_id=team_id, public_id=alert_id):
        raise AlertDestinationValidationError(
            "This alert's PagerDuty incident may still be open. Try again once the alert has resolved.",
            field="type",
        )


def _refuse_partly_paused(
    team_id: int, alert_id: UUID, allowed_event_ids: Collection[str], hog_function_ids: Collection[UUID]
) -> None:
    """A row is on or off for every event it hears, so it cannot keep some of a destination's events paused."""
    enabled = {
        destination.hog_function_id
        for destination in list_owned_alert_destinations(
            team_id=team_id,
            alert_ids=[str(alert_id)],
            allowed_event_ids=allowed_event_ids,
            template_ids=SPEC_BY_TEMPLATE_ID.keys(),
            enabled=True,
        )
    }.intersection(hog_function_ids)
    if enabled and len(enabled) < len(set(hog_function_ids)):
        raise AlertDestinationValidationError(
            "Some of this destination's events are paused. Turn them all on or all off, then reset it.",
            field="hog_function_ids",
        )


# The types whose URL carries the channel's credential in its path.
_URL_CREDENTIAL_TYPES = frozenset({DestinationType.WEBHOOK, DestinationType.DISCORD, DestinationType.TEAMS})


def _kept_secret(
    config: AlertDestinationConfig, data: AlertDestinationData, *, enabled: bool
) -> AlertDestinationConfig:
    """The config, with what the row kept encrypted kept encrypted: the URL becomes a secret input, and
    stored headers, such as an auth token, go in the webhook template's secret headers."""
    payload = {**config.payload, "enabled": enabled}
    destination_type = DestinationType(data["type"])
    if destination_type in _URL_CREDENTIAL_TYPES and "inputs_schema" not in payload:
        spec = DESTINATION_SPECS[destination_type]
        payload["inputs_schema"] = with_secret_inputs(spec.template_id, spec.address_input_keys)
    if stored := data.get("webhook_headers"):
        payload["inputs"] = {**payload["inputs"], "secret_headers": {"value": dict(stored)}}
    return replace(config, payload=payload)


# What the standard message cannot do the same way: send to another address, sign, use another method,
# or render a header. A reset that dropped one would change where or how the destination is reached.
# Message, body, code and filter edits are what a reset is for, so they do not block it.
_DELIVERY_HOLD_BACKS: Final = frozenset(
    {
        DestinationHoldBack.NO_TEMPLATE,
        DestinationHoldBack.OTHER_TEMPLATE,
        DestinationHoldBack.REFUSED_ADDRESS,
        DestinationHoldBack.TEMPLATED_ADDRESS,
        DestinationHoldBack.WEBHOOK_METHOD,
        DestinationHoldBack.WEBHOOK_SIGNING,
        DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER,
    }
)


def _refuse_what_the_standard_message_cannot_send(
    team_id: int, alert_id: UUID, allowed_event_ids: Collection[str], hog_function_ids: Collection[UUID]
) -> None:
    named = set(hog_function_ids)
    classified = [
        eligibility
        for eligibility in classify_alert_destinations(
            team_id=team_id, alert_id=str(alert_id), allowed_event_ids=allowed_event_ids
        )
        if eligibility.hog_function_id in named
    ]
    if {eligibility.hog_function_id for eligibility in classified} != named:
        # A HogFunction the classifier skips never received the alert's events, so nothing says the
        # standard message may reach its address.
        raise AlertDestinationValidationError(
            "This destination doesn't receive this alert's notifications, so it can't be reset.",
            field="hog_function_ids",
        )
    blocking = {
        hold_back
        for eligibility in classified
        for hold_back in eligibility.hold_backs
        if hold_back in _DELIVERY_HOLD_BACKS
    }
    if blocking:
        raise AlertDestinationValidationError(
            "The standard message can't reach this destination the way it does now "
            f"({', '.join(sorted(blocking))}). Change that in the destination's editor, then reset it.",
            field="hog_function_ids",
        )


def _with_secret_headers(
    team_id: int, data: AlertDestinationData, hog_function_ids: Collection[UUID]
) -> AlertDestinationData:
    """A webhook's settings with every header its HogFunctions send, as the standard message would send
    them: an added header and a secret one merged by name, ignoring case, the secret one winning, as the
    HogFunction does. Refused when a header cannot be sent natively or the HogFunctions disagree."""
    if data["type"] != DestinationType.WEBHOOK:
        return data
    sent_headers: list[dict[str, str]] = []
    for inputs, encrypted in HogFunction.objects.filter(team_id=team_id, id__in=list(hog_function_ids)).values_list(
        "inputs", "encrypted_inputs"
    ):
        stored = stored_inputs(inputs, encrypted)
        by_name: dict[str, tuple[str, str]] = {}
        for headers in (input_value(stored, "headers") or {}, input_value(stored, "secret_headers") or {}):
            for name, value in headers.items():
                if WEBHOOK_HEADERS.get(name) != value:
                    by_name[str(name).lower()] = (name, value)
        merged = dict(by_name.values())
        sendable = added_webhook_headers(merged)
        if len(sendable) != len(merged):
            raise AlertDestinationValidationError(
                "This webhook sends a header the standard message can't send.", field="hog_function_ids"
            )
        sent_headers.append(sendable)
    if any(headers != sent_headers[0] for headers in sent_headers):
        raise AlertDestinationValidationError(
            "This webhook sends different headers for different events. Make them match, then reset it.",
            field="hog_function_ids",
        )
    restored = cast(AlertDestinationData, {**data})
    restored.pop("webhook_headers", None)
    if sent_headers and sent_headers[0]:
        restored["webhook_headers"] = sent_headers[0]
    return restored

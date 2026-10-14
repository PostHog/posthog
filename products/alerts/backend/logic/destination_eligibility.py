"""Which alert destinations native delivery can take over without changing what they send.

A destination is a HogFunction a person can edit. Native delivery reads only where a destination
sends, so an edit to what it sends would be dropped silently at cutover. This finds those edits.

An edit is found by comparing a function with the first snapshot of its content, which the
HogFunction API writes on the first change it records. A template's stock text changes over time,
so comparing with what the code builds today would read an old, unedited function as edited.

The first snapshot is the stock content only when the function was created with stock inputs. The
logs alert API creates every logs destination that way. The HogFunction editor that insight alerts
use lets a person change the message before the first save, so for insight a function without a
later edit can still be customized.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from products.alerts.backend.facade.contracts import DestinationEligibility, DestinationHoldBack
from products.alerts.backend.logic.destination_configs import (
    SPEC_BY_TEMPLATE_ID,
    WEBHOOK_HEADERS,
    WebhookDestination,
    added_webhook_headers,
    input_value,
)
from products.alerts.backend.logic.destinations import _allowed_event_filter, owned_alert_destinations_qs
from products.alerts_platform.backend.facade.delivery import refused_destination
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

# The HogFunction API records edits from this date. A function built earlier and saved again has
# no record of what changed.
EDIT_TRACKING_STARTED: Final = datetime(2026, 8, 4, tzinfo=UTC)
# A function is saved in the moments after it is built. A later save means a person changed it.
RESAVED_AFTER: Final = timedelta(seconds=60)

_WEBHOOK_INPUT_HOLD_BACKS: Final = {
    "body": DestinationHoldBack.WEBHOOK_BODY,
    "method": DestinationHoldBack.WEBHOOK_METHOD,
}

_DERIVED_FILTER_KEYS: Final = ("bytecode", "bytecode_error", "bytecode_contract", "transpiled")


# Only these receive alert events. Any other function on the same event id reads captured events.
_RECEIVES_ALERT_EVENTS: Final = {"type": "internal_destination", "filters__source": "internal-events"}


def classify_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> tuple[DestinationEligibility, ...]:
    """Every destination function of one alert, with what native delivery cannot carry for each."""
    functions = list(
        owned_alert_destinations_qs(
            team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids, known_templates_only=False
        )
        .filter(**_RECEIVES_ALERT_EVENTS)
        .order_by("created_at", "id")
    )
    first_revisions: dict[UUID, HogFunctionRevision] = {
        revision.hog_function_id: revision
        for revision in HogFunctionRevision.objects.for_team(team_id)
        .filter(hog_function_id__in=[function.id for function in functions])
        .order_by("hog_function_id", "version")
        .distinct("hog_function_id")
        .only("hog_function_id", "content", "created_at")
    }
    return tuple(
        DestinationEligibility(
            hog_function_id=function.id,
            template_id=function.template_id,
            hold_backs=_hold_backs(function, first_revisions.get(function.id)),
        )
        for function in functions
    )


def unbound_alert_destinations(*, team_id: int, allowed_event_ids: Collection[str]) -> tuple[UUID, ...]:
    """Enabled functions that take a source's alert events without being bound to one alert.

    Such a function fires for many alerts of the team. Native delivery reads destinations per
    alert, so it would stop sending at cutover. A function bound to a deleted alert receives
    nothing, so it is not unbound.
    """
    candidates = (
        HogFunction.objects.filter(
            _allowed_event_filter(allowed_event_ids),
            team_id=team_id,
            deleted=False,
            enabled=True,
            **_RECEIVES_ALERT_EVENTS,
        )
        .order_by("created_at", "id")
        .values_list("id", "filters")
    )
    return tuple(function_id for function_id, filters in candidates if not _bound_to_one_alert(filters))


def _bound_to_one_alert(filters: Any) -> bool:
    # Only an exact match on one alert id scopes a function to that alert. Any other operator,
    # such as `is_not`, still lets it fire for other alerts.
    properties = filters.get("properties") if isinstance(filters, dict) else None
    return any(
        isinstance(prop, dict)
        and prop.get("key") == "alert_id"
        and prop.get("operator", "exact") == "exact"
        and isinstance(prop.get("value"), str)
        for prop in properties or ()
    )


def _hold_backs(function: HogFunction, first_revision: HogFunctionRevision | None) -> tuple[DestinationHoldBack, ...]:
    template_id = function.template_id or ""
    spec = SPEC_BY_TEMPLATE_ID.get(template_id)
    if spec is None:
        return (DestinationHoldBack.UNRECOGNIZED_TEMPLATE,)

    found: list[DestinationHoldBack] = []
    if function.masking:
        found.append(DestinationHoldBack.MASKING)
    if function.mappings:
        found.append(DestinationHoldBack.MAPPINGS)
    # A secret input is not in `inputs` or in a snapshot, so it is read where it is stored.
    if template_id == WebhookDestination.template_id and input_value(function.encrypted_inputs or {}, "signing_secret"):
        found.append(DestinationHoldBack.WEBHOOK_SIGNING)
    # A secret address, such as a PagerDuty routing key, is stored in `encrypted_inputs`.
    stored_inputs = {**(function.inputs or {}), **(function.encrypted_inputs or {})}
    if any(_has_template(input_value(stored_inputs, key)) for key in spec.address_input_keys):
        found.append(DestinationHoldBack.TEMPLATED_ADDRESS)
    elif refused_destination(spec.read(stored_inputs)) is not None:
        found.append(DestinationHoldBack.REFUSED_ADDRESS)

    # The first revision holds the config as it stood at the first tracked edit, so an earlier
    # untracked save is already inside it and the snapshot is no stock baseline.
    last_untracked_save = function.updated_at if first_revision is None else first_revision.created_at
    if function.created_at < EDIT_TRACKING_STARTED and last_untracked_save - function.created_at > RESAVED_AFTER:
        found.append(DestinationHoldBack.UNTRACKED_EDIT)
    if first_revision is None:
        return tuple(found)

    first_snapshot = first_revision.content

    if function.hog != first_snapshot.get("hog"):
        found.append(DestinationHoldBack.CODE)
    if function.inputs_schema != first_snapshot.get("inputs_schema"):
        found.append(DestinationHoldBack.CUSTOM_INPUTS)
    if _without_derived(function.filters) != _without_derived(first_snapshot.get("filters")):
        found.append(DestinationHoldBack.FILTERS)
    found.extend(_input_hold_backs(template_id, function.inputs or {}, first_snapshot.get("inputs") or {}))
    # Ordered and unique, so a report reads the same for the same function.
    return tuple(dict.fromkeys(found))


def _input_hold_backs(
    template_id: str, inputs: dict[str, Any], first_inputs: dict[str, Any]
) -> list[DestinationHoldBack]:
    found: list[DestinationHoldBack] = []
    is_webhook = template_id == WebhookDestination.template_id
    for key in sorted(set(inputs) | set(first_inputs)):
        if key in SPEC_BY_TEMPLATE_ID[template_id].address_input_keys:
            continue
        value, first_value = input_value(inputs, key), input_value(first_inputs, key)
        if is_webhook and key == "headers":
            # Native delivery sends the added headers that `added_webhook_headers` keeps, so only one
            # it drops changes what reaches the receiver.
            if value != first_value:
                dropped = _dropped_headers(value)
                if any(_has_template(header_value) for header_value in dropped.values()):
                    found.append(DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER)
                elif dropped:
                    found.append(DestinationHoldBack.WEBHOOK_HEADERS)
            continue
        if value == first_value and _templating(inputs, key) == _templating(first_inputs, key):
            continue
        if is_webhook and key in _WEBHOOK_INPUT_HOLD_BACKS:
            found.append(_WEBHOOK_INPUT_HOLD_BACKS[key])
        else:
            found.append(DestinationHoldBack.MESSAGE)
    return found


def _templating(inputs: dict[str, Any], key: str) -> Any:
    # The renderer follows this mode, so the same value renders differently under another one.
    entry = inputs.get(key)
    # The renderer reads an omitted mode as Hog, and the editor writes `hog` explicitly on save.
    templating = entry.get("templating") if isinstance(entry, dict) else None
    return templating or "hog"


def _dropped_headers(headers: Any) -> dict[str, Any]:
    if not isinstance(headers, dict):
        return {}
    kept = {name.lower() for name in added_webhook_headers(headers)}
    owned = {name.lower() for name in WEBHOOK_HEADERS}
    return {
        name: value
        for name, value in headers.items()
        if not isinstance(name, str) or (name.strip().lower() not in kept and name.strip().lower() not in owned)
    }


def _has_template(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_template(item) for item in value.values())
    return isinstance(value, str) and "{" in value


def _without_derived(filters: Any) -> Any:
    if not isinstance(filters, dict):
        return filters
    return {key: value for key, value in filters.items() if key not in _DERIVED_FILTER_KEYS}

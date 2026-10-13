"""Which alert destinations native delivery can take over without changing what they send.

A destination is a HogFunction a person can edit. Native delivery reads only where a destination
sends, so an edit to what it sends would be dropped silently at cutover. This finds those edits.

An edit is found by comparing a function with the first snapshot of its content, which the
HogFunction API writes on the first change it records. A template's stock text changes over time,
so comparing with what the code builds today would read an old, unedited function as edited.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from products.alerts.backend.facade.contracts import DestinationEligibility, DestinationHoldBack
from products.alerts.backend.logic.destination_configs import SPEC_BY_TEMPLATE_ID
from products.alerts.backend.logic.destinations import owned_alert_destinations_qs
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision

# The HogFunction API records edits from this date. A function built earlier and saved again has
# no record of what changed.
EDIT_TRACKING_STARTED: Final = datetime(2026, 8, 4, tzinfo=UTC)
# A function is saved in the moments after it is built. A later save means a person changed it.
RESAVED_AFTER: Final = timedelta(seconds=60)

# Where each template sends. Native delivery reads these, so a change to them is not an edit.
_ADDRESS_INPUT_KEYS: Final[dict[str, frozenset[str]]] = {
    "template-slack": frozenset({"slack_workspace", "channel"}),
    "template-webhook": frozenset({"url"}),
    "template-microsoft-teams": frozenset({"webhookUrl"}),
    "template-discord": frozenset({"webhookUrl"}),
    "template-pagerduty": frozenset({"routing_key", "severity", "region"}),
}

_WEBHOOK_INPUT_HOLD_BACKS: Final = {
    "body": DestinationHoldBack.WEBHOOK_BODY,
    "method": DestinationHoldBack.WEBHOOK_METHOD,
}

_DERIVED_FILTER_KEYS: Final = ("bytecode", "bytecode_error", "bytecode_contract", "transpiled")


def classify_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> tuple[DestinationEligibility, ...]:
    """Every destination function of one alert, with what native delivery cannot carry for each."""
    functions = list(
        owned_alert_destinations_qs(
            team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids, known_templates_only=False
        ).order_by("created_at", "id")
    )
    first_snapshots: dict[Any, dict[str, Any]] = {}
    for revision in (
        HogFunctionRevision.objects.for_team(team_id)
        .filter(hog_function_id__in=[function.id for function in functions])
        .order_by("hog_function_id", "version")
    ):
        first_snapshots.setdefault(revision.hog_function_id, revision.content)
    return tuple(
        DestinationEligibility(
            hog_function_id=function.id,
            template_id=function.template_id,
            hold_backs=_hold_backs(function, first_snapshots.get(function.id)),
        )
        for function in functions
    )


def _hold_backs(function: HogFunction, first_snapshot: dict[str, Any] | None) -> tuple[DestinationHoldBack, ...]:
    template_id = function.template_id or ""
    if template_id not in SPEC_BY_TEMPLATE_ID:
        return (DestinationHoldBack.UNRECOGNIZED_TEMPLATE,)

    found: list[DestinationHoldBack] = []
    if function.masking:
        found.append(DestinationHoldBack.MASKING)
    if function.mappings:
        found.append(DestinationHoldBack.MAPPINGS)
    # A secret input is not in `inputs` or in a snapshot, so it is read where it is stored.
    if template_id == "template-webhook" and _input_value(function.encrypted_inputs or {}, "signing_secret"):
        found.append(DestinationHoldBack.WEBHOOK_SIGNING)

    if first_snapshot is None:
        if function.created_at < EDIT_TRACKING_STARTED and function.updated_at - function.created_at > RESAVED_AFTER:
            found.append(DestinationHoldBack.UNTRACKED_EDIT)
        return tuple(found)

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
    for key in sorted(set(inputs) | set(first_inputs)):
        if key in _ADDRESS_INPUT_KEYS.get(template_id, frozenset()):
            continue
        value, first_value = _input_value(inputs, key), _input_value(first_inputs, key)
        if template_id == "template-webhook" and key == "headers":
            # Native delivery sends plain added headers. Only a templated value is lost.
            if value != first_value and _has_template(value):
                found.append(DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER)
            continue
        if value == first_value:
            continue
        if template_id == "template-webhook" and key in _WEBHOOK_INPUT_HOLD_BACKS:
            found.append(_WEBHOOK_INPUT_HOLD_BACKS[key])
        else:
            found.append(DestinationHoldBack.MESSAGE)
    return found


def _input_value(inputs: dict[str, Any], key: str) -> Any:
    entry = inputs.get(key)
    return entry.get("value") if isinstance(entry, dict) else entry


def _has_template(headers: Any) -> bool:
    return isinstance(headers, dict) and any(isinstance(value, str) and "{" in value for value in headers.values())


def _without_derived(filters: Any) -> Any:
    if not isinstance(filters, dict):
        return filters
    return {key: value for key, value in filters.items() if key not in _DERIVED_FILTER_KEYS}

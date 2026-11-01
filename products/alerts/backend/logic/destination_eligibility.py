"""Which alert destinations native delivery can take over without changing what they send.

A destination is a HogFunction a person can edit. Native delivery reads only where a destination
sends, so an edit to what it sends would be dropped silently at cutover. This finds those edits.

An edit is found by comparing a function with the first snapshot of its content, which the
HogFunction API writes on the first change it records. A template's stock text changes over time,
so comparing with what the code builds today would read an old, unedited function as edited.

The first snapshot is the stock content only when the function was created with stock inputs. The
HogFunction editor and API let a person write their own message before the first save, for insight
and logs destinations alike. So the first inputs are also compared with every default that the alert
paths of the source have shipped.
"""

from __future__ import annotations

import json
import hashlib
from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from products.alerts.backend.facade.contracts import (
    INSIGHT_ALERT_EVENT_IDS,
    DestinationBucket,
    DestinationEligibility,
    DestinationHoldBack,
)
from products.alerts.backend.logic.destination_configs import (
    SPEC_BY_TEMPLATE_ID,
    WEBHOOK_HEADERS,
    SlackDestination,
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

# An edited input missing here changes the message.
_INPUT_HOLD_BACKS: Final[dict[str, dict[str, DestinationHoldBack]]] = {
    WebhookDestination.template_id: {
        "body": DestinationHoldBack.WEBHOOK_BODY,
        "method": DestinationHoldBack.WEBHOOK_METHOD,
    },
    SlackDestination.template_id: {
        "icon_emoji": DestinationHoldBack.MESSAGE_COSMETIC,
        "username": DestinationHoldBack.MESSAGE_COSMETIC,
    },
}

# Every value an insight alert path has shipped as a default, by template and input key. Built from
# git history: the insight alert sub-template, the template defaults, the alert wizard, the backend
# Slack blocks, the agent recipes and the chart-block backfill. Add the default of any new path here.
StockInputValues = dict[str, dict[str, list[Any]]]


def _load_stock_input_values(file_name: str) -> StockInputValues:
    return json.loads((Path(__file__).parent / file_name).read_text())


STOCK_INPUT_VALUES: Final = _load_stock_input_values("destination_stock_inputs.json")
# Every value a logs alert path has written as a default, by template and input key: what the logs
# alert API builds, and the retired Slack messages that functions built in April 2026 still hold. When
# a logs message changes, add the new value and keep the old one, because functions built with it still exist.
LOGS_STOCK_INPUT_VALUES: Final = _load_stock_input_values("logs_destination_stock_inputs.json")
# Matches the logs events that `GENERIC_API_EDITABLE_ALERT_EVENT_SCOPES` in cdp names.
_LOGS_ALERT_EVENT_PREFIX: Final = "$logs_alert_"
_NOT_SENT_INPUTS: Final = frozenset({"debug"})

_DERIVED_FILTER_KEYS: Final = ("bytecode", "bytecode_error", "bytecode_contract", "transpiled")


_BUCKET_BY_HOLD_BACK: Final = {
    DestinationHoldBack.REFUSED_ADDRESS: DestinationBucket.REFUSED_ADDRESS,
    DestinationHoldBack.NO_TEMPLATE: DestinationBucket.CODE,
    DestinationHoldBack.CODE: DestinationBucket.CODE,
    DestinationHoldBack.MESSAGE_COSMETIC: DestinationBucket.COSMETIC,
    DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER: DestinationBucket.TEMPLATED_HEADERS,
    DestinationHoldBack.WEBHOOK_HEADERS: DestinationBucket.STATIC_HEADERS,
}
_BUCKET_ORDER: Final = tuple(DestinationBucket)


# The alert-id match is an OR of JSON containment clauses, so a team's alerts are read in batches.
_ALERT_BATCH_SIZE: Final = 200

# Only these receive alert events. Any other function on the same event id reads captured events.
_RECEIVES_ALERT_EVENTS: Final = {"type": "internal_destination", "filters__source": "internal-events"}
# Compiled code and drafts are large and never classified, so they stay unread.
_UNCLASSIFIED_FIELDS: Final = ("bytecode", "transpiled", "draft")


def classify_alert_destinations(
    *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
) -> tuple[DestinationEligibility, ...]:
    """Every destination function of one alert, with what native delivery cannot carry for each."""
    functions = (
        owned_alert_destinations_qs(
            team_id=team_id, alert_ids=[alert_id], allowed_event_ids=allowed_event_ids, known_templates_only=False
        )
        .filter(**_RECEIVES_ALERT_EVENTS)
        .defer(*_UNCLASSIFIED_FIELDS)
        .order_by("created_at", "id")
    )
    return _classify(team_id, list(functions), allowed_event_ids)


def classify_destinations_by_alert(
    *, team_id: int, alert_ids: Sequence[str], allowed_event_ids: Collection[str]
) -> dict[str, tuple[DestinationEligibility, ...]]:
    """The destination functions of several alerts of one team, keyed by alert id."""
    by_alert: dict[str, list[DestinationEligibility]] = {alert_id: [] for alert_id in alert_ids}
    for start in range(0, len(alert_ids), _ALERT_BATCH_SIZE):
        batch = set(alert_ids[start : start + _ALERT_BATCH_SIZE])
        functions = list(
            owned_alert_destinations_qs(
                team_id=team_id, alert_ids=batch, allowed_event_ids=allowed_event_ids, known_templates_only=False
            )
            .filter(**_RECEIVES_ALERT_EVENTS)
            .defer(*_UNCLASSIFIED_FIELDS)
            .order_by("created_at", "id")
        )
        for function, eligibility in zip(functions, _classify(team_id, functions, allowed_event_ids)):
            for alert_id in _named_alert_ids(function.filters) & batch:
                by_alert[alert_id].append(eligibility)
    return {alert_id: tuple(eligibilities) for alert_id, eligibilities in by_alert.items()}


def classify_unbound_alert_destinations(
    *, team_id: int, allowed_event_ids: Collection[str]
) -> tuple[DestinationEligibility, ...]:
    """Every unbound destination function of a team, with what native delivery cannot carry for each."""
    unbound_ids = unbound_alert_destinations(team_id=team_id, allowed_event_ids=allowed_event_ids)
    if not unbound_ids:
        return ()
    return _classify(
        team_id,
        list(HogFunction.objects.filter(team_id=team_id, id__in=unbound_ids).order_by("created_at", "id")),
        allowed_event_ids,
    )


def _classify(
    team_id: int, functions: list[HogFunction], allowed_event_ids: Collection[str]
) -> tuple[DestinationEligibility, ...]:
    if not functions:
        return ()
    source_stock = _source_stock_input_values(allowed_event_ids)
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
            hold_backs=_hold_backs(
                function, first_revisions.get(function.id), _template_stock(source_stock, function.template_id)
            ),
            code_hash=hashlib.md5((function.hog or "").encode(), usedforsecurity=False).hexdigest(),
        )
        for function in functions
    )


def _source_stock_input_values(allowed_event_ids: Collection[str]) -> StockInputValues | None:
    # The first revision of an insight or logs destination can already hold an edit.
    if not set(allowed_event_ids).isdisjoint(INSIGHT_ALERT_EVENT_IDS):
        return STOCK_INPUT_VALUES
    if any(event_id.startswith(_LOGS_ALERT_EVENT_PREFIX) for event_id in allowed_event_ids):
        return LOGS_STOCK_INPUT_VALUES
    return None


def _template_stock(source_stock: StockInputValues | None, template_id: str | None) -> dict[str, list[Any]] | None:
    if source_stock is None:
        return None
    # A template missing from the list was never a default of the source, so every message it holds is an edit.
    return source_stock.get(template_id or "", {})


def unrevised_hold_backs(
    template_id: str, inputs: dict[str, Any], allowed_event_ids: Collection[str]
) -> tuple[DestinationHoldBack, ...]:
    stock = _template_stock(_source_stock_input_values(allowed_event_ids), template_id)
    if stock is None:
        return ()
    return tuple(dict.fromkeys(_stock_hold_backs(template_id, inputs, stock)))


def bucket_for(eligibility: DestinationEligibility) -> DestinationBucket:
    """The most restrictive bucket among a destination's hold-backs. No hold-back means stock."""
    buckets = {_BUCKET_BY_HOLD_BACK.get(hold_back, DestinationBucket.PORTABLE) for hold_back in eligibility.hold_backs}
    return min(buckets, key=_BUCKET_ORDER.index, default=DestinationBucket.STOCK)


def unbound_alert_destinations(
    *, team_id: int, allowed_event_ids: Collection[str], include_disabled: bool = False
) -> tuple[UUID, ...]:
    """Functions that take a source's alert events without being bound to one alert, enabled ones only by default.

    Such a function fires for many alerts of the team. Native delivery reads destinations per
    alert, so it would stop sending at cutover. A function bound to a deleted alert receives
    nothing, so it is not unbound.
    """
    enabled = {} if include_disabled else {"enabled": True}
    candidates = (
        HogFunction.objects.filter(
            _allowed_event_filter(allowed_event_ids),
            team_id=team_id,
            deleted=False,
            **enabled,
            **_RECEIVES_ALERT_EVENTS,
        )
        .order_by("created_at", "id")
        .values_list("id", "filters")
    )
    return tuple(function_id for function_id, filters in candidates if not _bound_to_one_alert(filters))


def _named_alert_ids(filters: Any) -> set[str]:
    # Matches `owned_alert_destinations_qs`, which reads an alert id under any operator.
    properties = filters.get("properties") if isinstance(filters, dict) else None
    return {
        prop["value"]
        for prop in properties or ()
        if isinstance(prop, dict) and prop.get("key") == "alert_id" and isinstance(prop.get("value"), str)
    }


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


def _hold_backs(
    function: HogFunction, first_revision: HogFunctionRevision | None, stock: dict[str, list[Any]] | None
) -> tuple[DestinationHoldBack, ...]:
    template_id = function.template_id
    if not template_id:
        return (DestinationHoldBack.NO_TEMPLATE,)
    code_edited = first_revision is not None and function.hog != first_revision.content.get("hog")
    spec = SPEC_BY_TEMPLATE_ID.get(template_id)
    if spec is None:
        return (DestinationHoldBack.OTHER_TEMPLATE, *((DestinationHoldBack.CODE,) if code_edited else ()))

    found: list[DestinationHoldBack] = []
    if function.masking:
        found.append(DestinationHoldBack.MASKING)
    if function.mappings:
        found.append(DestinationHoldBack.MAPPINGS)
    # A secret input is not in `inputs` or in a snapshot, so it is read where it is stored.
    if template_id == WebhookDestination.template_id and input_value(function.encrypted_inputs or {}, "signing_secret"):
        found.append(DestinationHoldBack.WEBHOOK_SIGNING)
    # Native delivery reads ordinary headers only, so a secret header such as a token never reaches the receiver.
    if template_id == WebhookDestination.template_id and input_value(function.encrypted_inputs or {}, "secret_headers"):
        found.append(DestinationHoldBack.WEBHOOK_HEADERS)
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
    if stock is not None:
        first_inputs = function.inputs if first_revision is None else first_revision.content.get("inputs")
        found.extend(_stock_hold_backs(template_id, first_inputs or {}, stock))
    if first_revision is not None:
        first_snapshot = first_revision.content
        if code_edited:
            found.append(DestinationHoldBack.CODE)
        if function.inputs_schema != first_snapshot.get("inputs_schema"):
            found.append(DestinationHoldBack.CUSTOM_INPUTS)
        if _without_derived(function.filters) != _without_derived(first_snapshot.get("filters")):
            found.append(DestinationHoldBack.FILTERS)
        found.extend(
            _input_hold_backs(template_id, function.inputs or {}, first_snapshot.get("inputs") or {}, stock or {})
        )
    # Ordered and unique, so a report reads the same for the same function.
    return tuple(dict.fromkeys(found))


def _input_hold_backs(
    template_id: str, inputs: dict[str, Any], first_inputs: dict[str, Any], stock: dict[str, list[Any]]
) -> list[DestinationHoldBack]:
    found: list[DestinationHoldBack] = []
    for key in _compared_keys(template_id, set(inputs) | set(first_inputs)):
        value, first_value = input_value(inputs, key), input_value(first_inputs, key)
        same_mode = _is_webhook_headers(template_id, key) or _templating(inputs, key) == _templating(first_inputs, key)
        # A move from one shipped default to another, such as a bulk update to a newer stock
        # message, is not an edit a person made.
        if (value == first_value and same_mode) or _is_stock_value(inputs, key, stock):
            continue
        found.extend(_key_hold_backs(template_id, key, value))
    return found


def _stock_hold_backs(
    template_id: str, inputs: dict[str, Any], stock: dict[str, list[Any]]
) -> list[DestinationHoldBack]:
    found: list[DestinationHoldBack] = []
    for key in _compared_keys(template_id, set(inputs)):
        value = input_value(inputs, key)
        # The templates skip an empty input, so it sends what a missing one sends.
        if value in (None, "") or _is_stock_value(inputs, key, stock):
            continue
        found.extend(_key_hold_backs(template_id, key, value))
    # Without a body the webhook template sends none, but native delivery always sends one.
    if template_id == WebhookDestination.template_id and input_value(inputs, "body") in (None, ""):
        found.append(DestinationHoldBack.WEBHOOK_BODY)
    return found


def _is_stock_value(inputs: dict[str, Any], key: str, stock: dict[str, list[Any]]) -> bool:
    return input_value(inputs, key) in stock.get(key, ()) and _templating(inputs, key) == "hog"


def _compared_keys(template_id: str, keys: set[str]) -> list[str]:
    skipped = SPEC_BY_TEMPLATE_ID[template_id].address_input_keys | _NOT_SENT_INPUTS
    return sorted(keys - skipped)


def _is_webhook_headers(template_id: str, key: str) -> bool:
    return template_id == WebhookDestination.template_id and key == "headers"


def _key_hold_backs(template_id: str, key: str, value: Any) -> list[DestinationHoldBack]:
    if _is_webhook_headers(template_id, key):
        return _header_hold_backs(value)
    return [_INPUT_HOLD_BACKS.get(template_id, {}).get(key, DestinationHoldBack.MESSAGE)]


def _header_hold_backs(headers: Any) -> list[DestinationHoldBack]:
    # Native delivery sends the added headers that `added_webhook_headers` keeps, so only one it
    # drops changes what reaches the receiver.
    dropped = _dropped_headers(headers)
    if any(_has_template(header_value) for header_value in dropped.values()):
        return [DestinationHoldBack.WEBHOOK_TEMPLATED_HEADER]
    return [DestinationHoldBack.WEBHOOK_HEADERS] if dropped else []


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

"""Moves the stock destinations of a team's platform-owned insight alerts off HogFunctions.

Each stock HogFunction group becomes one `AlertDestination` row that copies it, and the group's
HogFunctions are retired in the same transaction. Delivery skips a row while any HogFunction it
copies exists, so the row starts sending only once they are gone, and never beside them. A row the
alert page already wrote for the group is kept, with its id, and rewritten from the group's live
settings. A group that several rows copy has them replaced by one new row.

This mirrors `products/logs/backend/destination_conversion.py`. Insight differs in what it leaves on
HogFunctions, because a row must not change what the receiver gets:

- PagerDuty: the native incident has another dedup key, source and details than the stock HogFunction's.
- A webhook whose stock HogFunction sends the legacy insight body: insight has no native legacy body,
  so a row would send the Alertmanager body instead.
- A group a Terraform state reads: retiring it deletes a `posthog_hog_function` resource under Terraform.

Each alert converts in its own transaction under its platform copy's lock, which a handback takes before
it changes the owner, then its HogFunctions' locks. A run is safe to repeat: a retired group is no longer
listed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import INSIGHT_ALERT_DESTINATION_EVENT_IDS
from products.alerts.backend.facade.destinations import (
    choose_delivery_path,
    classify_alert_destinations,
    configured_destination_template_ids,
    customized_alert_destination_ids,
    list_alert_destination_groups,
    list_owned_alert_destinations,
    lock_alert_destinations,
    soft_delete_alert_destinations,
)
from products.alerts.backend.logic.destinations import terraform_read_hog_function_ids
from products.alerts_platform.backend.facade.api import (
    copied_by_source_rows,
    delete_source_destination_rows,
    legacy_events_emitted_since,
    list_source_destinations,
    lock_source_configuration,
    native_configuration_keys,
    owned_copy_keys,
    record_source_destination,
    refresh_source_destination,
    runtime_by_public_id,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationGroup,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import DeliveryPath, PlatformAlertState

# An emitted event waits in the internal events queue until the CDP consumer picks its HogFunctions, so
# retiring them sooner loses a message the platform already counted as delivered.
LEGACY_EVENTS_QUIET_PERIOD = timedelta(minutes=15)

_ROW_EVENT_KINDS: tuple[AlertEventKind, ...] = (AlertEventKind.FIRING,)


class GroupOutcome(StrEnum):
    CONVERTED = "converted"
    KEPT_ROW = "kept_row"
    REPLACED_ROW = "replaced_row"
    CUSTOMIZED = "customized"
    TERRAFORM_HELD = "terraform_held"
    PAGERDUTY_NOT_NATIVE = "pagerduty_not_native"
    LEGACY_WEBHOOK_BODY = "legacy_webhook_body"
    FIRING = "firing"
    RECENTLY_EMITTED = "recently_emitted"
    PARTLY_ENABLED = "partly_enabled"
    PARTLY_COPIED = "partly_copied"
    REFUSED = "refused"
    NO_SOURCE_DESTINATIONS = "no_source_destinations"


SUCCESSFUL_OUTCOMES = frozenset({GroupOutcome.CONVERTED, GroupOutcome.KEPT_ROW, GroupOutcome.REPLACED_ROW})


@frozen
class GroupConversion:
    alert_id: UUID
    hog_function_ids: tuple[UUID, ...]
    outcome: GroupOutcome
    detail: str = ""


def convert_team(team_id: int, *, apply: bool) -> tuple[GroupConversion, ...]:
    """Converts the stock destinations of every platform-owned insight alert of one team. Without `apply`,
    each alert is decided as a real run would decide it, then its transaction is rolled back."""
    keys = [
        (key.created_at, key.legacy_configuration_id)
        for key in owned_copy_keys(team_id=team_id, source_kind=SourceKind.INSIGHT)
    ]
    keys += native_configuration_keys(team_id=team_id, source_kind=SourceKind.INSIGHT)
    return tuple(
        conversion for _, alert_id in sorted(keys) for conversion in _convert_alert(team_id, alert_id, apply=apply)
    )


def _convert_alert(team_id: int, alert_id: UUID, *, apply: bool) -> list[GroupConversion]:
    with transaction.atomic():
        try:
            lock_source_configuration(team_id=team_id, public_id=alert_id)
            # Only an alert the platform owns is listed, so a handback between listing and locking drops it.
            runtime = runtime_by_public_id(team_id=team_id, public_ids=[alert_id]).get(alert_id)
            if runtime is None:
                return []
            lock_alert_destinations(
                team_id=team_id, alert_id=str(alert_id), allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS
            )
            candidates = _stock_candidates(team_id, alert_id)
            if not candidates:
                return []
            whole_alert_outcome = None
            if runtime.state == PlatformAlertState.FIRING:
                whole_alert_outcome = GroupOutcome.FIRING
            elif legacy_events_emitted_since(
                team_id=team_id, public_id=alert_id, since=timezone.now() - LEGACY_EVENTS_QUIET_PERIOD
            ):
                whole_alert_outcome = GroupOutcome.RECENTLY_EMITTED
            if whole_alert_outcome is not None:
                # A Terraform-held group stays held after the firing ends, so the summary counts it as held.
                return [
                    GroupConversion(
                        alert_id=alert_id,
                        hog_function_ids=group.hog_function_ids,
                        outcome=GroupOutcome.TERRAFORM_HELD if facts.terraform_held else whole_alert_outcome,
                    )
                    for group, facts in candidates
                ]
            # On the HogFunction path a stock webhook sends the legacy insight body, which no row can send.
            # Read before any group moves.
            webhook_sends_legacy_body = (
                choose_delivery_path(
                    source=SourceKind.INSIGHT,
                    team_id=team_id,
                    alert_id=str(alert_id),
                    allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS,
                )
                == DeliveryPath.HOG_FUNCTION
            )
            groups = [group for group, _ in candidates]
            return [
                _convert_group(
                    team_id, alert_id, group, facts, groups, webhook_sends_legacy_body=webhook_sends_legacy_body
                )
                for group, facts in candidates
            ]
        finally:
            # After the last query, because a block marked for rollback refuses queries.
            if not apply:
                transaction.set_rollback(True)


@frozen
class _GroupFacts:
    customized: bool
    terraform_held: bool
    enabled_count: int
    data: AlertDestinationData


def _stock_candidates(team_id: int, alert_id: UUID) -> list[tuple[AlertDestinationGroup, _GroupFacts]]:
    alert_key = str(alert_id)
    receives_alert_events = {
        eligibility.hog_function_id
        for eligibility in classify_alert_destinations(
            team_id=team_id, alert_id=alert_key, allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS
        )
    }
    # A function on the same event id that reads captured events is not the alert's destination, and the
    # customized check never classifies it, so it would otherwise convert as stock.
    groups = [
        group
        for group in list_alert_destination_groups(
            team_id=team_id, alert_id=alert_key, allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS
        )
        if receives_alert_events.issuperset(group.hog_function_ids)
    ]
    if not groups:
        return []
    customized = customized_alert_destination_ids(
        team_id=team_id, alert_id=alert_key, allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS
    )
    terraform_read = terraform_read_hog_function_ids(
        team_id=team_id, hog_function_ids=[i for group in groups for i in group.hog_function_ids]
    )
    data_by_group = {
        listed.hog_function_ids: listed.data
        for listed in list_source_destinations(team_id=team_id, public_id=alert_id, hog_function_groups=groups)
    }
    enabled_ids = {
        owned.hog_function_id
        for owned in list_owned_alert_destinations(
            team_id=team_id,
            alert_ids=[alert_key],
            allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS,
            template_ids=configured_destination_template_ids(
                team_id=team_id, alert_id=alert_key, allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS
            ),
            enabled=True,
        )
    }
    return [
        (
            group,
            _GroupFacts(
                customized=not customized.isdisjoint(group.hog_function_ids),
                terraform_held=not terraform_read.isdisjoint(group.hog_function_ids),
                enabled_count=len(enabled_ids.intersection(group.hog_function_ids)),
                data=data_by_group.get(group.hog_function_ids, group.data),
            ),
        )
        for group in groups
    ]


def _convert_group(
    team_id: int,
    alert_id: UUID,
    group: AlertDestinationGroup,
    facts: _GroupFacts,
    groups: Sequence[AlertDestinationGroup],
    *,
    webhook_sends_legacy_body: bool,
) -> GroupConversion:
    def result(outcome: GroupOutcome, detail: str = "") -> GroupConversion:
        return GroupConversion(
            alert_id=alert_id, hog_function_ids=group.hog_function_ids, outcome=outcome, detail=detail
        )

    if facts.terraform_held:
        return result(GroupOutcome.TERRAFORM_HELD)
    if facts.customized:
        return result(GroupOutcome.CUSTOMIZED)
    if facts.data["type"] == DestinationType.PAGERDUTY:
        return result(GroupOutcome.PAGERDUTY_NOT_NATIVE)
    if facts.data["type"] == DestinationType.WEBHOOK and webhook_sends_legacy_body:
        return result(GroupOutcome.LEGACY_WEBHOOK_BODY)
    if 0 < facts.enabled_count < len(group.hog_function_ids):
        return result(GroupOutcome.PARTLY_ENABLED)
    copied = copied_by_source_rows(team_id=team_id, public_id=alert_id, hog_function_ids=group.hog_function_ids)
    if copied and copied != set(group.hog_function_ids):
        return result(GroupOutcome.PARTLY_COPIED)

    try:
        with transaction.atomic():
            outcome = _write_row(team_id, alert_id, group, facts, groups, copied)
            # A queryset update, not a save: a HogFunction saved as deleted deletes every row that copies it.
            soft_delete_alert_destinations(
                team_id=team_id,
                alert_id=str(alert_id),
                allowed_event_ids=INSIGHT_ALERT_DESTINATION_EVENT_IDS,
                hog_function_ids=list(group.hog_function_ids),
            )
    except AlertDestinationValidationError as error:
        return result(GroupOutcome.REFUSED, str(error))
    except _NoSourceDestinations:
        return result(GroupOutcome.NO_SOURCE_DESTINATIONS)
    return result(outcome)


def _write_row(
    team_id: int,
    alert_id: UUID,
    group: AlertDestinationGroup,
    facts: _GroupFacts,
    groups: Sequence[AlertDestinationGroup],
    copied: frozenset[UUID],
) -> GroupOutcome:
    enabled = facts.enabled_count > 0
    if copied:
        kept = refresh_source_destination(
            team_id=team_id,
            public_id=alert_id,
            data=facts.data,
            event_kinds=_ROW_EVENT_KINDS,
            hog_function_ids=group.hog_function_ids,
            hog_function_groups=groups,
            enabled=enabled,
            keeps_legacy_webhook_body=False,
        )
        if kept is not None:
            return GroupOutcome.KEPT_ROW
        delete_source_destination_rows(team_id=team_id, public_id=alert_id, destination_ids=(), hog_function_ids=copied)
    recorded = record_source_destination(
        team_id=team_id,
        public_id=alert_id,
        data=facts.data,
        event_kinds=_ROW_EVENT_KINDS,
        hog_function_ids=group.hog_function_ids,
        # Every group, so a second group that sends to the same place keeps both on HogFunctions.
        hog_function_groups=groups,
        enabled=enabled,
    )
    if recorded is None:
        raise _NoSourceDestinations
    return GroupOutcome.REPLACED_ROW if copied else GroupOutcome.CONVERTED


class _NoSourceDestinations(Exception):
    """Raised inside the group's savepoint, so a row deleted for replacement comes back."""

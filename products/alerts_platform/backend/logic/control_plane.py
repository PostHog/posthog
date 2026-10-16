"""Ends the firings a control-plane change leaves behind, and closes their incidents.

Disabling an alert, snoozing it, changing what it checks or deleting it ends any firing it is in, as
on the logs stack. An incident manager needs one resolve for every trigger, and no later check would
send it: discovery skips a disabled or snoozed alert, and a deleted one is gone. So the change writes
the end of each firing to history and sends the resolve itself. Only an incident destination acts on
it, so no message goes out, as the logs stack sends only its incident close.
"""

import math
from dataclasses import replace
from datetime import datetime

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    IncidentAction,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.facade.grouping import MAX_TRANSITIONS_PER_DELIVERY
from products.alerts_platform.backend.logic import source_configs
from products.alerts_platform.backend.logic.platform_alert_events import PlatformAlertEventRow, insert_events
from products.alerts_platform.backend.logic.platform_lifecycle import condition_snapshot
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

logger = structlog.get_logger(__name__)


@frozen
class PendingClose:
    """The history rows and the resolve that ending an alert's firings owes, sent once they stand."""

    team_id: int
    rows: tuple[PlatformAlertEventRow, ...]
    delivery: AlertDeliveryRequest | None


def end_firings(configuration: PlatformAlertConfiguration, *, reason: str, now: datetime) -> PendingClose | None:
    """Moves every firing instance of a configuration locked by the caller to not firing.

    Call it before the change is saved, so the history rows state the settings the firing ran under.
    None when nothing was firing.
    """
    firing = list(
        PlatformAlert.objects.for_team(configuration.team_id, canonical=True).filter(
            configuration=configuration, state=PlatformAlertState.FIRING
        )
    )
    if not firing:
        return None
    # Unique per change, because a delivery addresses its rows by this key.
    evaluation_key = f"control:{reason}:{now.isoformat()}"
    rows = tuple(
        PlatformAlertEventRow(
            team_id=configuration.team_id,
            source_kind=configuration.source_kind,
            configuration_id=configuration.id,
            alert_id=alert.id,
            grouping_key=alert.grouping_key,
            evaluation_key=evaluation_key,
            kind=AlertEventKind.CHECK.value,
            alert_name=configuration.name,
            previous_state=PlatformAlertState.FIRING.value,
            state=PlatformAlertState.NOT_FIRING.value,
            # The episode the trigger named, which is the incident a resolve has to name.
            episode_started_at=alert.firing_started_at,
            value=None,
            labels={},
            condition_snapshot=condition_snapshot(configuration),
            source_config_snapshot=configuration.source_config,
            query_duration_ms=None,
            error_message=None,
            consecutive_failures=configuration.consecutive_failures,
            muted_notification="",
            occurred_at=now,
        )
        for alert in firing
    )
    for alert in firing:
        alert.state = PlatformAlertState.NOT_FIRING
        alert.firing_started_at = None
    PlatformAlert.objects.bulk_update(firing, ["state", "firing_started_at"])
    return PendingClose(
        team_id=configuration.team_id,
        rows=rows,
        delivery=_resolve_delivery(configuration, evaluation_key, [alert.grouping_key for alert in firing]),
    )


def _resolve_delivery(
    configuration: PlatformAlertConfiguration, evaluation_key: str, grouping_keys: list[str]
) -> AlertDeliveryRequest | None:
    spec = source_configs.spec(SourceKind(configuration.source_kind))
    if spec is None or spec.incident_address is None or configuration.legacy_configuration_id is None:
        return None
    address = spec.incident_address(
        team_id=configuration.team_id, legacy_configuration_id=configuration.legacy_configuration_id
    )
    if address is None:
        return None
    return AlertDeliveryRequest(
        source=SourceKind(configuration.source_kind),
        team_id=configuration.team_id,
        configuration_id=str(configuration.id),
        evaluation_key=evaluation_key,
        destination_alert_id=address.destination_alert_id,
        event_ids_by_kind={},
        incident_actions=dict.fromkeys(grouping_keys, IncidentAction.RESOLVE),
        sends_messages=False,
        event_ids_by_incident_action=address.event_ids_by_incident_action,
        source_alert_url=address.source_alert_url,
        owned_by_platform=True,
        parts=max(1, math.ceil(len(grouping_keys) / MAX_TRANSITIONS_PER_DELIVERY)),
    )


def announce_after_commit(pending: PendingClose | None) -> None:
    """Writes the history and starts the resolve's delivery once the change commits."""
    if pending is not None:
        transaction.on_commit(lambda: _announce(pending), robust=True)


def _announce(pending: PendingClose) -> None:
    insert_events(pending.team_id, pending.rows)
    if pending.delivery is not None:
        # Imported here because the facade that reaches this module loads in processes that never
        # start a workflow, and the starter loads the Temporal client.
        from products.alerts_platform.backend.temporal.web_start import (  # noqa: PLC0415 - keeps the Temporal client off the import path
            start_delivery,
        )

        start_delivery(pending.delivery)


def announce_now(pending: PendingClose | None) -> None:
    """Writes the history and sends the resolve before returning, for a change that is about to
    remove the destinations a later delivery would look up."""
    if pending is None:
        return
    insert_events(pending.team_id, pending.rows)
    if pending.delivery is None:
        return
    # Imported here for the same reason as the starter: delivery loads every transport.
    from products.alerts_platform.backend.delivery.evaluation import (  # noqa: PLC0415 - keeps the transports off the import path
        deliver_evaluation,
    )

    for part in range(pending.delivery.parts):
        try:
            deliver_evaluation(replace(pending.delivery, part=part))
        except Exception as error:
            # The change goes ahead. A resolve that could not be sent leaves the incident open, which
            # error tracking shows.
            capture_exception(error, {"configuration_id": pending.delivery.configuration_id})

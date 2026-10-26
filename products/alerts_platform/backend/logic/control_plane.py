"""Ends the firings a control-plane change leaves behind, and closes their incidents.

Disabling an alert, snoozing it, changing what it checks or deleting it ends any firing it is in, as
on the logs stack. An incident manager needs one resolve for every trigger, and no later check would
send it: discovery skips a disabled or snoozed alert, and a deleted one is gone. So the change writes
the end of each firing to history and sends the resolve itself. Only an incident destination acts on
it, so no message goes out, as the logs stack sends only its incident close.
"""

from datetime import datetime
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    IncidentAction,
    PlatformAlertConfigurationEdit,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.facade.grouping import parts_for
from products.alerts_platform.backend.logic import source_configs
from products.alerts_platform.backend.logic.platform_alert_events import PlatformAlertEventRow
from products.alerts_platform.backend.logic.platform_lifecycle import end_firing_instances, event_row, record_history
from products.alerts_platform.backend.models import PlatformAlertConfiguration

# The settings whose change makes a firing meaningless, as a threshold or filter change does on the
# logs stack. A rename or a quiet-hours change leaves it running.
_DECIDING_SETTINGS = ("source_config", "evaluation_periods", "datapoints_to_alarm")


def ending_reason(
    current: PlatformAlertConfigurationEdit, edit: PlatformAlertConfigurationEdit, *, regrouped: bool, snoozing: bool
) -> str | None:
    """Why an edit ends the alert's firings, or None. In the logs stack's order: a disable wins over a
    snooze, which wins over a change to what the alert checks."""
    if current.enabled and not edit.enabled:
        return "disabled"
    if snoozing:
        return "snoozed"
    if regrouped:
        return "regrouped"
    if any(getattr(current, field) != getattr(edit, field) for field in _DECIDING_SETTINGS):
        return "config_changed"
    return None


@frozen
class PendingClose:
    """The history rows and the resolve that ending an alert's firings owes, sent once they stand."""

    team_id: int
    source_kind: str
    configuration_id: UUID
    legacy_configuration_id: UUID | None
    rows: tuple[PlatformAlertEventRow, ...]


def end_firings(configuration: PlatformAlertConfiguration, *, reason: str, now: datetime) -> PendingClose | None:
    """Moves every firing instance of a configuration locked by the caller to not firing.

    Call it before the change is saved, so the history rows state the settings the firing ran under.
    None when nothing was firing.
    """
    firing = end_firing_instances(configuration, now=now)
    if not firing:
        return None
    # Unique per change, because a delivery addresses its rows by this key.
    evaluation_key = f"control:{reason}:{now.isoformat()}"
    rows = tuple(
        event_row(
            configuration,
            alert=alert,
            evaluation_key=evaluation_key,
            kind=AlertEventKind.CHECK.value,
            previous_state=PlatformAlertState.FIRING.value,
            state=PlatformAlertState.NOT_FIRING.value,
            # The episode the trigger named, which is the incident a resolve has to name.
            episode_started_at=alert.firing_started_at,
            consecutive_failures=configuration.consecutive_failures,
            now=now,
        )
        for alert in firing
    )
    return PendingClose(
        team_id=configuration.team_id,
        source_kind=configuration.source_kind,
        configuration_id=configuration.id,
        legacy_configuration_id=configuration.legacy_configuration_id,
        rows=rows,
    )


def announce_after_commit(pending: PendingClose | None) -> None:
    """Writes the history and starts the resolve's delivery once the change commits."""
    if pending is not None:
        transaction.on_commit(lambda: _announce(pending, inline=False), robust=True)


def announce_now(pending: PendingClose | None) -> None:
    """Writes the history and sends the resolve before returning, for a change about to remove the
    destinations a later delivery would look up."""
    if pending is not None:
        _announce(pending, inline=True)


def _announce(pending: PendingClose, *, inline: bool) -> None:
    # A delivery reads its rows back from history, so the rows go first.
    record_history(pending.team_id, pending.rows)
    delivery = _resolve_delivery(pending)
    if delivery is None:
        return
    # Imported here because this module loads in processes that never send, and the sender loads the
    # Temporal client and every transport.
    from products.alerts_platform.backend.temporal.web_start import (  # noqa: PLC0415 - keeps Temporal and the transports off the import path
        deliver,
        deliver_inline,
    )

    if inline:
        deliver_inline(delivery)
    else:
        deliver(delivery)


def _resolve_delivery(pending: PendingClose) -> AlertDeliveryRequest | None:
    spec = source_configs.spec(SourceKind(pending.source_kind))
    if spec is None or spec.incident_event_ids is None or pending.legacy_configuration_id is None:
        return None
    grouping_keys = [row.grouping_key for row in pending.rows]
    return AlertDeliveryRequest(
        source=SourceKind(pending.source_kind),
        team_id=pending.team_id,
        configuration_id=str(pending.configuration_id),
        evaluation_key=pending.rows[0].evaluation_key,
        # The id the source's destinations are matched on, as on every check's delivery.
        destination_alert_id=str(pending.legacy_configuration_id),
        event_ids_by_kind={},
        incident_actions=dict.fromkeys(grouping_keys, IncidentAction.RESOLVE),
        sends_messages=False,
        event_ids_by_incident_action=dict(spec.incident_event_ids),
        source_alert_url=spec.alert_url(pending.team_id, pending.legacy_configuration_id) if spec.alert_url else None,
        owned_by_platform=True,
        parts=parts_for(len(grouping_keys)),
    )

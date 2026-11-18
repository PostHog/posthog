"""A follow-up about a firing that already went out, such as an investigation that changed its verdict.

A check announces once, and history is append-only, so a verdict that arrives after the firing's
message cannot change what that row said. The follow-up gets a row of its own, under its own
evaluation key, with the firing's episode. That episode puts the reply in the firing's thread and
sends it on the firing's delivery path.

The write is that row and nothing else. It moves no state, no schedule and no notified time,
because the check that fired already moved them.
"""

from datetime import datetime

from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    SourceKind,
    VerdictChange,
    VerdictChangeNotRecorded,
)
from products.alerts_platform.backend.logic import delivery_holds
from products.alerts_platform.backend.logic.platform_lifecycle import RULE_METADATA_FIELDS, event_row, record_history
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


def record_verdict_change(change: VerdictChange, *, now: datetime) -> AlertDeliveryRequest | None:
    """Records the follow-up's row and returns the delivery to start, or None when there is nothing to send.

    None when the configuration or its group is gone, or when the firing is still held or was
    suppressed. Raises `VerdictChangeNotRecorded` when ClickHouse refused the row.
    """
    alert = (
        PlatformAlert.objects.for_team(change.team_id)
        .select_related("configuration")
        .defer(*(f"configuration__{name}" for name in RULE_METADATA_FIELDS))
        .filter(configuration_id=change.configuration_id, grouping_key=change.grouping_key)
        .first()
    )
    if alert is None:
        return None
    # A reply to a firing nobody received would arrive with no message above it.
    if delivery_holds.blocks_delivery(change.team_id, str(change.configuration_id), change.firing_evaluation_key):
        return None
    configuration = alert.configuration

    row = event_row(
        configuration,
        alert=alert,
        evaluation_key=change.evaluation_key,
        kind=AlertEventKind.VERDICT_CHANGED.value,
        previous_state=alert.state,
        state=alert.state,
        episode_started_at=change.episode_started_at,
        labels=alert.labels,
        consecutive_failures=configuration.consecutive_failures,
        now=now,
        source_detail=change.source_detail,
    )
    if not record_history(change.team_id, [row]):
        raise VerdictChangeNotRecorded(f"no history row for {change.evaluation_key}")
    return AlertDeliveryRequest(
        source=SourceKind(configuration.source_kind),
        team_id=change.team_id,
        configuration_id=str(configuration.id),
        evaluation_key=change.evaluation_key,
        destination_alert_id=str(configuration.destination_alert_id),
        # The firing's event, so a HogFunction that sent the firing sends the follow-up, as legacy does.
        event_ids_by_kind={AlertEventKind.VERDICT_CHANGED.value: change.firing_event_id},
        source_alert_url=change.source_alert_url,
        owned_by_platform=configuration.owner == PlatformAlertConfiguration.Owner.PLATFORM,
    )

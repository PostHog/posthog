"""The inbox signal an insight firing asks for in its `source_detail`, emitted after the record.

A check only marks that its firing starts an episode the agent never investigates, because its
evaluation can be retried. The evaluation workflow emits the signal once the firing is recorded.
This module has no Django imports, so the workflow can call it.
"""

from datetime import datetime
from typing import Final

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import PlatformAlertOutcome

# The public id of the alert whose firing files the signal: its insight stack row's, or the
# configuration's own when it has no row.
FIRING_SIGNAL_REQUESTED_KEY: Final = "firing_signal_alert_id"
# Set when errors came before the firing, so the emit activity reads whether they interrupted one.
FIRING_SIGNAL_AFTER_ERRORS_KEY: Final = "firing_signal_after_errors"


@frozen
class FiringSignalRequest:
    """A recorded firing that starts an episode, as the emit activity reads it."""

    team_id: int
    alert_id: str
    configuration_id: str
    episode_started_at: datetime
    breaches: tuple[str, ...] = ()
    triggered_dates: tuple[str, ...] = ()
    after_errors: bool = False
    grouping_key: str = ""
    investigable: bool = True


def requested_firing_signals(
    team_id: int, outcomes: tuple[PlatformAlertOutcome, ...]
) -> tuple[FiringSignalRequest, ...]:
    """The signals the recorded outcomes ask for. Only a firing that starts an episode asks for one, and
    a breakdown alert asks for one per value that starts its own."""
    requests = []
    for outcome in outcomes:
        for group in outcome.groups:
            alert_id = group.source_detail.get(FIRING_SIGNAL_REQUESTED_KEY)
            episode = group.firing_episode
            if alert_id is None or episode is None or episode.started_at is None:
                continue
            requests.append(
                FiringSignalRequest(
                    team_id=team_id,
                    alert_id=str(alert_id),
                    configuration_id=str(outcome.configuration_id),
                    episode_started_at=episode.started_at,
                    breaches=tuple(str(breach) for breach in group.source_detail.get("breaches") or ()),
                    triggered_dates=tuple(str(date) for date in group.source_detail.get("triggered_dates") or ()),
                    after_errors=bool(group.source_detail.get(FIRING_SIGNAL_AFTER_ERRORS_KEY)),
                    grouping_key=group.grouping_key,
                    investigable=len(outcome.groups) == 1,
                )
            )
    return tuple(requests)

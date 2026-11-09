"""The Inbox signal an insight firing asks for in its `source_detail`, sent after the record.

A check only marks the firing that starts an episode, because its evaluation can be retried. The
evaluation workflow sends the signal once the firing is recorded. This module has no Django
imports, so the workflow can call it.
"""

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import PlatformAlertOutcome

FIRING_SIGNAL_REQUESTED_KEY = "firing_signal_requested"


@frozen
class FiringSignalRequest:
    team_id: int
    configuration_id: str
    evaluation_key: str
    episode_started_at: str | None
    breaches: tuple[str, ...] = ()
    triggered_dates: tuple[str, ...] = ()


def requested_firing_signals(
    team_id: int, outcomes: tuple[PlatformAlertOutcome, ...]
) -> tuple[FiringSignalRequest, ...]:
    """The signal each recorded outcome asks for. At most one per outcome, because the episode is the alert's."""
    requests: list[FiringSignalRequest] = []
    for outcome in outcomes:
        group = next((group for group in outcome.groups if group.source_detail.get(FIRING_SIGNAL_REQUESTED_KEY)), None)
        if group is None:
            continue
        started_at = group.firing_episode.started_at if group.firing_episode else None
        requests.append(
            FiringSignalRequest(
                team_id=team_id,
                configuration_id=str(outcome.configuration_id),
                evaluation_key=outcome.evaluation_key,
                episode_started_at=started_at.isoformat() if started_at else None,
                breaches=tuple(str(breach) for breach in group.source_detail.get("breaches") or ()),
                triggered_dates=tuple(str(date) for date in group.source_detail.get("triggered_dates") or ()),
            )
        )
    return tuple(requests)

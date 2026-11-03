"""The investigation an insight firing asks for in its `source_detail`, claimed after the record.

A check only decides that its firing gets an investigation, because its evaluation can be retried.
The evaluation workflow claims it once the firing is recorded, and starts the agent. This module
has no Django imports, so the workflow can call it.
"""

from datetime import datetime

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, PlatformAlertOutcome

# The legacy alert whose agent investigates the firing. Recorded with the firing, so history shows
# which checks asked for an investigation.
INVESTIGATION_REQUESTED_KEY = "investigation_alert_id"
# The same, for a metrics alert, whose investigation is a few metric queries rather than an agent run.
METRICS_INVESTIGATION_REQUESTED_KEY = "metrics_investigation_alert_id"
# Marks a firing the episode's last verdict muted, so the history tells it from a snooze.
SUPPRESSED_BY_AGENT_KEY = "notification_suppressed_by_agent"


@frozen
class InvestigationStart:
    """An agent run the claim granted, as the workflow starts it."""

    team_id: int
    alert_id: str
    investigation_id: str
    configuration_id: str
    evaluation_key: str
    user_id: int | None = None

    @property
    def workflow_id(self) -> str:
        return f"anomaly-investigation-{self.configuration_id}:{self.evaluation_key}"

    def workflow_inputs(self) -> dict[str, object]:
        """The agent's `AnomalyInvestigationWorkflowInputs`, as JSON. The agent's module imports Django,
        which the workflow sandbox refuses, so the inputs cross by name."""
        return {
            "team_id": self.team_id,
            "alert_id": self.alert_id,
            "investigation_id": self.investigation_id,
            "user_id": self.user_id,
        }


@frozen
class MetricsInvestigationRun:
    """A metrics investigation the claim granted, which the workflow runs in an activity of its own."""

    team_id: int
    investigation_id: str
    # The firing the run explains, whose held delivery the run releases once it ends.
    configuration_id: str = ""
    evaluation_key: str = ""


@frozen
class InvestigationClaims:
    starts: tuple[InvestigationStart, ...] = ()
    # Held firings whose claim was refused, released by the firing's last verdict and due to start.
    deliveries: tuple[AlertDeliveryRequest, ...] = ()
    metrics: tuple[MetricsInvestigationRun, ...] = ()


@frozen
class RequestedInvestigation:
    alert_id: str
    episode_started_at: datetime | None
    metrics: bool = False


def requested_investigation(outcome: PlatformAlertOutcome) -> RequestedInvestigation | None:
    """The investigation an outcome asks for, or None. Only an ungrouped firing asks for one."""
    for group in outcome.groups:
        started_at = group.firing_episode.started_at if group.firing_episode else None
        if (alert_id := group.source_detail.get(INVESTIGATION_REQUESTED_KEY)) is not None:
            return RequestedInvestigation(alert_id=str(alert_id), episode_started_at=started_at)
        if (alert_id := group.source_detail.get(METRICS_INVESTIGATION_REQUESTED_KEY)) is not None:
            return RequestedInvestigation(alert_id=str(alert_id), episode_started_at=started_at, metrics=True)
    return None

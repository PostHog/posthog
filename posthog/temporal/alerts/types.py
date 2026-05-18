import dataclasses
from enum import StrEnum

from posthog.schema import AlertState

from posthog.slo.types import SloConfig


class PrepareAction(StrEnum):
    EVALUATE = "evaluate"
    SKIP = "skip"
    AUTO_DISABLE = "auto_disable"


class SkipReason(StrEnum):
    NOT_FOUND = "not_found"
    DISABLED = "disabled"
    INSIGHT_DELETED = "insight_deleted"
    NOT_DUE = "not_due"
    WEEKEND = "weekend"
    QUIET_HOURS = "quiet_hours"
    SNOOZED = "snoozed"


@dataclasses.dataclass(frozen=True)
class AlertInfo:
    alert_id: str
    team_id: int
    distinct_id: str
    calculation_interval: str | None
    insight_id: int


@dataclasses.dataclass(frozen=True)
class CheckAlertWorkflowInputs:
    alert_id: str
    team_id: int
    distinct_id: str
    calculation_interval: str | None
    insight_id: int
    slo: SloConfig | None = None


@dataclasses.dataclass(frozen=True)
class PrepareAlertActivityInputs:
    alert_id: str


@dataclasses.dataclass(frozen=True)
class PrepareAlertResult:
    action: PrepareAction
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class EvaluateAlertActivityInputs:
    alert_id: str


@dataclasses.dataclass(frozen=True)
class EvaluateAlertResult:
    # AlertCheck PK is a UUIDT; stringified here so Temporal's JSON codec can pass it through.
    alert_check_id: str
    should_notify: bool
    new_state: AlertState
    # Human-readable breach descriptions the FIRING email uses as match_descriptions.
    # Not persisted on AlertCheck, so the workflow must pipe them from evaluate to notify.
    breaches: list[str] | None = None
    # Investigation agent is opted in and this fire claimed the cooldown slot. Workflow
    # should start the AnomalyInvestigationWorkflow as a child.
    should_start_investigation: bool = False
    # Hold the synchronous notification — the investigation workflow will dispatch it
    # itself after the verdict, or the safety-net schedule will force-fire on stall.
    should_gate_notification: bool = False
    # Persisted alert.created_by — the investigation workflow uses this to attribute
    # the resulting Notebook. Optional because legacy alerts may not have it.
    investigation_user_id: int | None = None


@dataclasses.dataclass(frozen=True)
class NotifyAlertActivityInputs:
    alert_id: str
    alert_check_id: str
    breaches: list[str] | None = None

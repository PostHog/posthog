import dataclasses
from enum import StrEnum

from posthog.schema import AlertState

from posthog.slo.types import SloConfig


class PrepareAction(StrEnum):
    EVALUATE = "evaluate"
    SKIP = "skip"
    AUTO_DISABLE = "auto_disable"


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
    alert_check_id: int
    should_notify: bool
    new_state: AlertState


@dataclasses.dataclass(frozen=True)
class NotifyAlertActivityInputs:
    alert_id: str
    alert_check_id: int

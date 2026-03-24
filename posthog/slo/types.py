import dataclasses
from enum import StrEnum
from typing import Optional


class SloArea(StrEnum):
    ANALYTIC_PLATFORM = "analytic-platform"


class SloOperation(StrEnum):
    EXPORT = "export"
    SUBSCRIPTION_DELIVERY = "subscription_delivery"
    ALERT_CHECK = "alert_check"


class SloOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclasses.dataclass
class SloStartedProperties:
    area: SloArea
    operation: SloOperation
    team_id: int
    resource_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


@dataclasses.dataclass
class SloCompletedProperties:
    area: SloArea
    operation: SloOperation
    team_id: int
    outcome: SloOutcome
    resource_id: Optional[str] = None
    duration_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

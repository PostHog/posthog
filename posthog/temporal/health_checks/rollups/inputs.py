from __future__ import annotations

from typing import Literal

from posthog.dataclasses import frozen

RollupStepMode = Literal["publish", "refresh"]
RollupStepOutcome = Literal["published", "unchanged"]


@frozen
class DailyRollupWorkflowInputs:
    tables: list[str] | None = None
    days: list[str] | None = None
    force: bool = False


@frozen
class RollupStep:
    table: str
    day: str
    mode: RollupStepMode
    force: bool = False


@frozen
class RollupPlan:
    steps: list[RollupStep]
    retention_tables: list[str]


@frozen
class RollupStepResult:
    table: str
    day: str
    outcome: RollupStepOutcome
    rows: int
    events: int

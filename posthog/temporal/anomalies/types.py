import dataclasses
from typing import Any


@dataclasses.dataclass
class DiscoverInsightsActivityInputs:
    recently_viewed_days: int = 30
    max_candidates: int = 500


@dataclasses.dataclass
class EligibleInsight:
    insight_id: int
    team_id: int
    interval: str  # hour, day, week, month


# -- Training types --


@dataclasses.dataclass
class ScheduleTrainingInputs:
    # Hard cap per scheduled training tick (hourly). Oldest `last_trained_at`
    # wins, so anything over this cap waits for the next hour — best-effort
    # drain rather than trying to refit the whole estate in one run.
    batch_size: int = 100
    max_concurrent: int = 5  # max child workflows running in parallel


@dataclasses.dataclass
class TrainInsightActivityInputs:
    insight_id: int
    team_id: int
    detector_config: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class TrainInsightWorkflowInputs:
    insight_id: int
    team_id: int
    detector_config: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class TrainInsightResult:
    insight_id: int
    trained: bool = False
    model_version: int = 0
    error: str | None = None


# -- Scoring types --


@dataclasses.dataclass
class ScheduleScoringInputs:
    # Hard cap per scheduled scoring tick (every 5 min). Most-overdue by
    # `next_score_due_at` wins; anything over the cap falls to the next tick.
    batch_size: int = 100
    max_concurrent: int = 10  # scoring is lighter, can run more in parallel


@dataclasses.dataclass
class ScoreInsightActivityInputs:
    insight_id: int
    team_id: int
    model_storage_key: str = ""
    detector_config: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ScoreInsightWorkflowInputs:
    insight_id: int
    team_id: int
    model_storage_key: str = ""
    detector_config: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ScoreInsightResult:
    insight_id: int
    scored: bool = False
    error: str | None = None


# -- Cleanup types --


@dataclasses.dataclass
class CleanupScoresActivityInputs:
    retention_days: int = 30

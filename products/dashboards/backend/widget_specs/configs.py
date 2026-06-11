from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from products.dashboards.backend.constants import DEFAULT_WIDGET_LIST_LIMIT
from products.dashboards.backend.widget_specs.common import WidgetLimit, WidgetListConfigBase, WidgetOrderDirection

ERROR_TRACKING_LIST_WIDGET_TYPE = "error_tracking_list"
SESSION_REPLAY_LIST_WIDGET_TYPE = "session_replay_list"
EXPERIMENTS_LIST_WIDGET_TYPE = "experiments_list"
EXPERIMENT_RESULTS_WIDGET_TYPE = "experiment_results"

ErrorTrackingOrderBy = Literal["last_seen", "first_seen", "occurrences", "users", "sessions"]
ErrorTrackingWidgetStatus = Literal["archived", "active", "resolved", "pending_release", "suppressed", "all"]
SessionReplayOrderBy = Literal[
    "start_time", "activity_score", "recording_duration", "duration", "click_count", "console_error_count"
]
WidgetAssigneeType = Literal["user", "role"]
ExperimentsWidgetStatus = Literal["draft", "running", "paused", "stopped", "all"]


class WidgetAssigneeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | int
    type: WidgetAssigneeType


class ErrorTrackingListWidgetConfig(WidgetListConfigBase):
    limit: WidgetLimit = Field(default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of issues to return.")
    orderBy: ErrorTrackingOrderBy = Field(default="occurrences", description="Issue ranking column.")
    orderDirection: WidgetOrderDirection = Field(default="DESC", description="Sort direction for orderBy.")
    status: ErrorTrackingWidgetStatus = Field(default="active", description="Issue status filter.")
    assignee: WidgetAssigneeFilter | None = Field(
        default=None,
        description="Filter by assignee ({type: user|role, id}). Omit for any assignee.",
    )


class SessionReplayListWidgetConfig(WidgetListConfigBase):
    limit: WidgetLimit = Field(default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of recordings to return.")
    orderBy: SessionReplayOrderBy = Field(default="start_time", description="Recording ranking column.")
    orderDirection: WidgetOrderDirection = Field(default="DESC", description="Sort direction for orderBy.")


class ExperimentsListWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: WidgetLimit = Field(
        default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of experiments to return."
    )
    status: ExperimentsWidgetStatus = Field(default="all", description="Experiment status filter.")
    createdBy: int | None = Field(default=None, description="Filter by creator (user id). Omit for any creator.")


class ExperimentResultsWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experimentId: int | None = Field(
        default=None,
        description="Experiment to show results for. Null until the user picks one in the widget settings.",
    )

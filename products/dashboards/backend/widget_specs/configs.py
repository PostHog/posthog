from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.dashboards.backend.constants import ACTIVITY_EVENTS_DEFAULT_LIMIT, DEFAULT_WIDGET_LIST_LIMIT
from products.dashboards.backend.widget_specs.common import (
    ActivityWidgetLimit,
    WidgetLimit,
    WidgetListConfigBase,
    WidgetOrderDirection,
)

ACTIVITY_EVENTS_LIST_WIDGET_TYPE = "activity_events_list"
ERROR_TRACKING_LIST_WIDGET_TYPE = "error_tracking_list"
SESSION_REPLAY_LIST_WIDGET_TYPE = "session_replay_list"

ErrorTrackingOrderBy = Literal["last_seen", "first_seen", "occurrences", "users", "sessions"]
ErrorTrackingWidgetStatus = Literal["archived", "active", "resolved", "pending_release", "suppressed", "all"]
SessionReplayOrderBy = Literal[
    "start_time", "activity_score", "recording_duration", "duration", "click_count", "console_error_count"
]
WidgetAssigneeType = Literal["user", "role"]


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
    savedFilterId: str | None = Field(
        default=None,
        description=(
            "short_id of a saved session replay filter to use as the recordings source. When set, the saved filter "
            "owns the date range and property filters; only orderBy, orderDirection, and limit still apply."
        ),
    )

    @field_validator("savedFilterId", mode="before")
    @classmethod
    def validate_saved_filter_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("savedFilterId must be a string.")
        return value


class ActivityEventsListWidgetConfig(WidgetListConfigBase):
    limit: ActivityWidgetLimit = Field(
        default=ACTIVITY_EVENTS_DEFAULT_LIMIT, description="Maximum number of events to return."
    )

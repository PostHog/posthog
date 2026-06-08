from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionSummaryReadyProperties(BaseModel):
    """Properties of the `$session_summary_ready` event."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    insert_id: str = Field(alias="$insert_id")
    session_id: str
    team_id: int
    summary_id: str
    session_summary: dict[str, Any]
    extra_summary_context: dict[str, Any] | None
    session_summary_focus_area: str | None
    replay_url: str
    model_used: str | None
    session_start_time: datetime | None
    session_duration: int | None

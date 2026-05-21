"""Pydantic OpenAPI types for alert quiet hours (schedule_restriction JSONField)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AlertScheduleRestrictionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = Field(
        ...,
        description=(
            "Start time HH:MM (24-hour, project timezone). Inclusive. "
            "Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end))."
        ),
    )
    end: str = Field(
        ...,
        description=(
            "End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally."
        ),
    )


class AlertScheduleRestriction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocked_windows: list[AlertScheduleRestrictionWindow] = Field(
        ...,
        description=(
            "Blocked local time windows when the alert must not run. "
            "Overlapping or identical windows are merged when saved. "
            "At most five windows before normalization; empty array clears quiet hours."
        ),
    )

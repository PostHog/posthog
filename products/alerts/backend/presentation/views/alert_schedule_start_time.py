"""Pydantic OpenAPI type for the alert schedule start time."""

from pydantic import BaseModel, ConfigDict, Field


class AlertScheduleStartTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str = Field(
        ...,
        description="Local project time in HH:MM format. The scheduler uses this time to start the alert cadence.",
    )

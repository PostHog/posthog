"""Pydantic OpenAPI type for the alert schedule anchor."""

from pydantic import BaseModel, ConfigDict, Field


class AlertScheduleAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str = Field(
        ...,
        description="Local project time in HH:MM format. The scheduler uses this time as the cadence anchor.",
    )

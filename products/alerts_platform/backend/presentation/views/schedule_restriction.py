"""Pydantic OpenAPI types for alert quiet hours (schedule_restriction JSONField).

The field belongs to this product's configuration, and adopter products reuse these to describe
their own alert APIs. They carry drf-spectacular meaning rather than data a consumer reads, so
they sit on the presentation surface, not in the facade.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from pydantic import BaseModel, ConfigDict, Field
from rest_framework import serializers


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


@extend_schema_field(AlertScheduleRestriction)  # type: ignore[arg-type]
class ScheduleRestrictionField(serializers.JSONField):
    """The quiet hours column, described to drf-spectacular by the model above.

    Every alert product declares this field, so it lives beside the type it points at rather
    than being redeclared once per adopter.
    """

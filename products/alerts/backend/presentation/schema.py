"""Presentation shapes and helpers that adopter products' own DRF views reuse.

The schedule-restriction models describe one JSON field in the generated OpenAPI spec, and
`as_drf_validation_error` turns the facade's framework-free destination error into a DRF one.
Neither is a contract: both carry DRF or drf-spectacular meaning, so they sit above the facade.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from rest_framework.exceptions import ValidationError

from products.alerts.backend.facade.contracts import AlertDestinationValidationError


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


def as_drf_validation_error(error: AlertDestinationValidationError) -> ValidationError:
    """The DRF equivalent of a destination validation error, keyed by field when it names one."""
    if error.field:
        return ValidationError({error.field: [error.message]})
    return ValidationError(error.message)

"""The schema an insight alert's `source_config` takes in the alerts platform's API, and the rules for
a whole edit.

Loaded on first use through `load_insight_source_config`, never from `ready()`, because it is built
on `posthog.schema`.
"""

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import AlertCondition, InsightThreshold

from products.alerts.backend.platform_ownership import mirror_platform_edit
from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)


class InsightPlatformAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: InsightThreshold | None = Field(
        ..., description="The bounds the insight's value is checked against, absolute or as a percentage change."
    )
    comparison: AlertCondition = Field(
        ...,
        description="How the value is compared: as it is, or as an increase or decrease from the previous interval.",
    )
    detector: None = Field(
        default=None, description="Always null. The platform owns threshold alerts only, so no detector applies."
    )


class InsightPlatformAlertSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight_id: int = Field(..., description="The insight the alert checks. It cannot change through this API.")
    condition: InsightPlatformAlertCondition = Field(
        ..., description="The bound the insight's value is checked against."
    )


def validate_insight_edit(edit: PlatformAlertConfigurationEdit) -> None:
    # The insight row has no place for these, and a value it cannot store would be lost on handback.
    if edit.grouping.mode != GroupingMode.SINGLE:
        raise InvalidPlatformAlertEdit("grouping", "An insight alert cannot be grouped through this API yet.")
    for name, value, stored in (
        ("evaluation_periods", edit.evaluation_periods, 1),
        ("datapoints_to_alarm", edit.datapoints_to_alarm, 1),
        ("cooldown_minutes", edit.cooldown_minutes, 0),
    ):
        if value != stored:
            raise InvalidPlatformAlertEdit(name, f"An insight alert keeps this at {stored}.")


INSIGHT_SOURCE_CONFIG = SourceConfigSpec(
    model=InsightPlatformAlertSourceConfig,
    validate=validate_insight_edit,
    mirror=mirror_platform_edit,
)

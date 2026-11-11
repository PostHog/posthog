"""The schema an insight alert's `source_config` takes in the alerts platform's API, and the rules for
a whole edit.

Loaded on first use through `load_insight_source_config`, never from `ready()`, because it is built
on `posthog.schema`.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import AlertCondition, InsightThreshold

from products.alerts.backend.facade.contracts import INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION
from products.alerts.backend.platform_insight_alert import INSIGHT_ROW_SETTINGS, RECURRENCE
from products.alerts.backend.platform_ownership import (
    admit_platform_write,
    guard_native_insight_edit,
    mirror_platform_edit,
    remove_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.alerts_platform.backend.facade.scheduling import MINUTES_PER_DAY


class InsightPlatformAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: InsightThreshold | None = Field(
        ..., description="The bounds the insight's value is checked against, absolute or as a percentage change."
    )
    comparison: AlertCondition = Field(
        ...,
        description="How the value is compared: as it is, or as an increase or decrease from the previous interval.",
    )
    detector: dict[str, Any] | None = Field(
        default=None,
        description="The anomaly detector the alert uses in place of its threshold, or null for a threshold alert. "
        "It can't change through this API.",
    )


class InsightPlatformAlertSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight_id: int = Field(..., description="The insight the alert checks. It cannot change through this API.")
    condition: InsightPlatformAlertCondition = Field(
        ..., description="The bound the insight's value is checked against."
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Which part of the insight the alert reads, such as the series and whether the current "
        "interval counts. It can't change through this API.",
    )
    skip_weekend: bool = Field(
        default=False, description="Whether checks skip Saturdays and Sundays. It can't change through this API."
    )
    evaluation_delay_intervals: int = Field(
        default=0,
        ge=0,
        description="How many of the most recent intervals a check leaves out, so late data can arrive. "
        "It can't change through this API.",
    )
    investigation_agent_enabled: bool = Field(
        default=False,
        description="Whether an AI agent investigates each firing of an anomaly alert. It can't change through this API.",
    )
    investigation_gates_notifications: bool = Field(
        default=False,
        description="Whether a firing waits for the agent's verdict, and is dropped when the agent calls it a "
        "false positive. It can't change through this API.",
    )
    investigation_inconclusive_action: Literal["notify", "suppress"] = Field(
        default="notify",
        description="What a waiting firing does when the agent's verdict is inconclusive. It can't change through this API.",
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


def creates_native_alert(team_id: int) -> bool:
    """No insight alert is created without an insight row yet."""
    return False


INSIGHT_SOURCE_CONFIG = SourceConfigSpec(
    model=InsightPlatformAlertSourceConfig,
    validate=validate_insight_edit,
    admit=admit_platform_write,
    mirror=mirror_platform_edit,
    # For an insight alert with no insight row: the platform deletes it, and its destinations stay
    # HogFunctions. Creates stay off, and out of the API schema, until `creates` and
    # `creates_native_alert` turn them on. A native create picks any insight cadence, daily by default.
    native=NativeAlertLifecycle(
        check_interval_minutes=MINUTES_PER_DAY,
        check_intervals=dict(RECURRENCE.values()),
        remove_destinations=remove_alert_destinations,
        creates=False,
    ),
    native_create=creates_native_alert,
    native_edit_guard=guard_native_insight_edit,
    incident_event_ids=INSIGHT_EVENT_IDS_BY_INCIDENT_ACTION,
    kept_source_config_keys=INSIGHT_ROW_SETTINGS,
)

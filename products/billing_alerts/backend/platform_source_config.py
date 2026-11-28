"""The `source_config` of a billing alert on the alerts platform."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BillingPlatformAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # In USD. An alert fires when the period total reaches it.
    threshold_value: Decimal = Field(ge=0, max_digits=20, decimal_places=6, allow_inf_nan=False)


class BillingPlatformAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal["spend", "projected_spend"]
    condition: BillingPlatformAlertCondition

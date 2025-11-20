# ruff: noqa: F405  # Star imports are intentional
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, RootModel

from posthog.schema.enums import *  # noqa: F403, F401

if TYPE_CHECKING:
    from posthog.schema.nodes import *  # noqa: F403, F401


class ExperimentFunnelMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_order_type: Optional[StepOrderValue] = None
    metric_type: Literal["funnel"] = "funnel"
    series: list[Union[EventsNode, ActionsNode]]


class ExperimentRatioMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    metric_type: Literal["ratio"] = "ratio"
    numerator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]


class ExperimentMeanMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ignore_zeros: Optional[bool] = None
    lower_bound_percentile: Optional[float] = None
    metric_type: Literal["mean"] = "mean"
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    upper_bound_percentile: Optional[float] = None


class ExperimentMetricTypeProps(
    RootModel[Union[ExperimentMeanMetricTypeProps, ExperimentFunnelMetricTypeProps, ExperimentRatioMetricTypeProps]]
):
    root: Union[ExperimentMeanMetricTypeProps, ExperimentFunnelMetricTypeProps, ExperimentRatioMetricTypeProps]

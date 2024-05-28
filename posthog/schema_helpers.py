from pydantic import BaseModel

from posthog.schema import (
    FunnelStepReference,
    FunnelsFilter,
    FunnelsQuery,
    FunnelVizType,
    FunnelConversionWindowTimeUnit,
    FunnelLayout,
    BreakdownAttributionType,
    StepOrderValue,
)


def clean_funnels_filter(funnelsFilter: FunnelsFilter | None) -> FunnelsFilter:
    if funnelsFilter is None:
        funnelsFilter = FunnelsFilter()

    # binCount: Optional[int] = None
    if funnelsFilter.funnelVizType != FunnelVizType.time_to_convert:
        funnelsFilter.binCount = None

    # breakdownAttributionType: Optional[BreakdownAttributionType] = None
    if funnelsFilter.breakdownAttributionType == BreakdownAttributionType.first_touch:
        funnelsFilter.breakdownAttributionType = None

    # breakdownAttributionValue: Optional[int] = None
    if funnelsFilter.breakdownAttributionType != BreakdownAttributionType.step:
        funnelsFilter.breakdownAttributionValue = None

    # exclusions: Optional[list[Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]]] = None
    if funnelsFilter.exclusions == []:
        funnelsFilter.exclusions = None

    # funnelAggregateByHogQL: Optional[str] = None
    if funnelsFilter.funnelAggregateByHogQL == "":
        funnelsFilter.funnelAggregateByHogQL = None

    # funnelFromStep: Optional[int] = None
    # funnelToStep: Optional[int] = None

    # funnelOrderType: Optional[StepOrderValue] = None
    if funnelsFilter.funnelOrderType == StepOrderValue.ordered:
        funnelsFilter.funnelOrderType = None

    # funnelStepReference: Optional[FunnelStepReference] = None
    if funnelsFilter.funnelStepReference == FunnelStepReference.total:
        funnelsFilter.funnelStepReference = None

    # funnelVizType: Optional[FunnelVizType] = None
    if funnelsFilter.funnelVizType == FunnelVizType.steps:
        funnelsFilter.funnelVizType = None

    # funnelWindowInterval: Optional[int] = None
    if funnelsFilter.funnelWindowInterval == 14:
        funnelsFilter.funnelWindowInterval = None

    # funnelWindowIntervalUnit: Optional[FunnelConversionWindowTimeUnit] = None
    if funnelsFilter.funnelWindowIntervalUnit == FunnelConversionWindowTimeUnit.day:
        funnelsFilter.funnelWindowIntervalUnit = None

    # hidden_legend_breakdowns: Optional[list[str]] = None
    if funnelsFilter.hidden_legend_breakdowns is not None:
        funnelsFilter.hidden_legend_breakdowns = None

    # layout: Optional[FunnelLayout] = None
    if funnelsFilter.layout == FunnelLayout.vertical:
        funnelsFilter.layout = None

    return funnelsFilter


def clean_query(query: FunnelsQuery) -> FunnelsQuery:
    query.funnelsFilter = clean_funnels_filter(query.funnelsFilter)
    return query


def to_json(query: BaseModel) -> str:
    if isinstance(query, FunnelsQuery):
        query = clean_query(query)
    return query.model_dump_json(exclude_defaults=True, exclude_none=True)

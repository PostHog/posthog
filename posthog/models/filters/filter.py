from .base_filter import BaseFilter
from .mixins.common import (
    BreakdownMixin,
    BreakdownValueMixin,
    ClientQueryIdMixin,
    CompareMixin,
    DateMixin,
    DisplayDerivedMixin,
    DistinctIdMixin,
    EmailMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityMathMixin,
    EntityOrderMixin,
    EntityTypeMixin,
    FilterTestAccountsMixin,
    FormulaMixin,
    IncludeRecordingsMixin,
    InsightMixin,
    LimitMixin,
    OffsetMixin,
    SampleMixin,
    SearchMixin,
    SelectorMixin,
    ShownAsMixin,
    SmoothingIntervalsMixin,
    UpdatedAfterMixin,
)
from .mixins.funnel import (
    FunnelCorrelationActorsMixin,
    FunnelCorrelationMixin,
    FunnelFromToStepsMixin,
    FunnelHogQLAggregationMixin,
    FunnelLayoutMixin,
    FunnelPersonsStepBreakdownMixin,
    FunnelPersonsStepMixin,
    FunnelTrendsPersonsMixin,
    FunnelTypeMixin,
    FunnelWindowDaysMixin,
    FunnelWindowMixin,
    HistogramMixin,
)
from .mixins.groups import GroupsAggregationMixin
from .mixins.interval import IntervalMixin
from .mixins.property import PropertyMixin
from .mixins.simplify import SimplifyFilterMixin


class Filter(
    PropertyMixin,
    IntervalMixin,
    SmoothingIntervalsMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityTypeMixin,
    EntityMathMixin,
    EntityOrderMixin,
    DisplayDerivedMixin,
    SelectorMixin,
    ShownAsMixin,
    BreakdownMixin,
    CompareMixin,
    BreakdownValueMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    OffsetMixin,
    LimitMixin,
    DateMixin,
    FormulaMixin,
    FunnelWindowDaysMixin,
    FunnelWindowMixin,
    FunnelFromToStepsMixin,
    FunnelPersonsStepMixin,
    FunnelTrendsPersonsMixin,
    FunnelPersonsStepBreakdownMixin,
    FunnelLayoutMixin,
    FunnelHogQLAggregationMixin,
    FunnelTypeMixin,
    HistogramMixin,
    GroupsAggregationMixin,
    FunnelCorrelationMixin,
    FunnelCorrelationActorsMixin,
    SimplifyFilterMixin,
    IncludeRecordingsMixin,
    SearchMixin,
    DistinctIdMixin,
    EmailMixin,
    UpdatedAfterMixin,
    ClientQueryIdMixin,
    SampleMixin,
    BaseFilter,
):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    pass

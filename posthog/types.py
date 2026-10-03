from typing import Union

from posthog.schema import (
    AccountCustomPropertyFilter,
    ActionsNode,
    BehavioralPropertyFilter,
    CohortPropertyFilter,
    DataWarehouseNode,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    ErrorTrackingIssueFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    ExperimentActorsQuery,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    FunnelCorrelationActorsQuery,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsActorsQuery,
    FunnelsDataWarehouseNode,
    FunnelsQuery,
    GroupNode,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    InsightActorsQuery,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    MetricPropertyFilter,
    PathsQuery,
    PathsV2ActorsQuery,
    PathsV2Query,
    PersonMetadataPropertyFilter,
    PersonPropertyFilter,
    RecordingPropertyFilter,
    RetentionQuery,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
    SpanPropertyFilter,
    StickinessActorsQuery,
    StickinessQuery,
    TrendsQuery,
    WorkflowVariablePropertyFilter,
)

from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter

type FilterType = Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
"""Legacy insight filters."""

type InsightQueryNode = Union[
    TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, PathsV2Query, StickinessQuery, LifecycleQuery
]

type InsightActorsQueryNode = Union[
    InsightActorsQuery,
    FunnelsActorsQuery,
    FunnelCorrelationActorsQuery,
    StickinessActorsQuery,
    ExperimentActorsQuery,
    PathsV2ActorsQuery,
]

type AnyPropertyFilter = Union[
    EventPropertyFilter,
    PersonPropertyFilter,
    PersonMetadataPropertyFilter,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    AccountCustomPropertyFilter,
    SessionPropertyFilter,
    LogEntryPropertyFilter,
    CohortPropertyFilter,
    RecordingPropertyFilter,
    GroupPropertyFilter,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
    MetricPropertyFilter,
    SpanPropertyFilter,
    WorkflowVariablePropertyFilter,
    BehavioralPropertyFilter,
]

type EntityNode = Union[
    EventsNode, ActionsNode, DataWarehouseNode, LifecycleDataWarehouseNode, FunnelsDataWarehouseNode, GroupNode
]
type FunnelEntityNode = Union[EventsNode, ActionsNode, FunnelsDataWarehouseNode, GroupNode]
type FunnelExclusionEntityNode = Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]

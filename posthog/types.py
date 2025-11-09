from typing import Union

from posthog.schema import (
    ActionsNode,
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
    FeaturePropertyFilter,
    FlagPropertyFilter,
    FunnelCorrelationActorsQuery,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsActorsQuery,
    FunnelsQuery,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    InsightActorsQuery,
    LifecycleQuery,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    PathsQuery,
    PathsV2Query,
    PersonPropertyFilter,
    RecordingPropertyFilter,
    RetentionQuery,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
    StickinessActorsQuery,
    StickinessQuery,
    TrendsQuery,
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
    InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery
]

type AnyPropertyFilter = Union[
    EventPropertyFilter,
    PersonPropertyFilter,
    ElementPropertyFilter,
    EventMetadataPropertyFilter,
    RevenueAnalyticsPropertyFilter,
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
]

type EntityNode = Union[EventsNode, ActionsNode, DataWarehouseNode]
type ExclusionEntityNode = Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]

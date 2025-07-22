from typing import TypeAlias, Union

from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    DataWarehouseNode,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    FeaturePropertyFilter,
    FlagDependencyPropertyFilter,
    FunnelCorrelationActorsQuery,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsActorsQuery,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    InsightActorsQuery,
    PersonPropertyFilter,
    RecordingPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
    LogEntryPropertyFilter,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
    StickinessActorsQuery,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
)

FilterType: TypeAlias = Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
"""Legacy insight filters."""

InsightQueryNode: TypeAlias = Union[
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
]

InsightActorsQueryNode: TypeAlias = Union[
    InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery
]

AnyPropertyFilter: TypeAlias = Union[
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
    FlagDependencyPropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
]

EntityNode: TypeAlias = Union[EventsNode, ActionsNode, DataWarehouseNode]
ExclusionEntityNode: TypeAlias = Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]

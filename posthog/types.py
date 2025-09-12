from typing import TypeAlias, Union

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
    FlagPropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
]

EntityNode: TypeAlias = Union[EventsNode, ActionsNode, DataWarehouseNode]
ExclusionEntityNode: TypeAlias = Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]

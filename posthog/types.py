from typing import TypeAlias, Union

from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    EventPropertyFilter,
    EventsNode,
    FeaturePropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    RecordingDurationFilter,
    SessionPropertyFilter,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
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

AnyPropertyFilter: TypeAlias = Union[
    EventPropertyFilter,
    PersonPropertyFilter,
    ElementPropertyFilter,
    SessionPropertyFilter,
    CohortPropertyFilter,
    RecordingDurationFilter,
    GroupPropertyFilter,
    FeaturePropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
]

EntityNode: TypeAlias = Union[EventsNode, ActionsNode]

from typing import Union

from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.schema import (
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
)

FilterType = Union[Filter, PathFilter, RetentionFilter, StickinessFilter]

InsightQueryNode = Union[
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
]

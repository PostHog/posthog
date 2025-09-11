from typing import TypeAlias

from .filter import Filter
from .path_filter import PathFilter
from .properties_timeline_filter import PropertiesTimelineFilter
from .retention_filter import RetentionFilter
from .stickiness_filter import StickinessFilter

__all__ = [
    "Filter",
    "PathFilter",
    "RetentionFilter",
    "StickinessFilter",
    "PropertiesTimelineFilter",
    "AnyFilter",
]

AnyFilter: TypeAlias = Filter | PathFilter | RetentionFilter | StickinessFilter | PropertiesTimelineFilter

AnyInsightFilter: TypeAlias = Filter | PathFilter | RetentionFilter | StickinessFilter

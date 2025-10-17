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

type AnyFilter = Filter | PathFilter | RetentionFilter | StickinessFilter | PropertiesTimelineFilter

type AnyInsightFilter = Filter | PathFilter | RetentionFilter | StickinessFilter

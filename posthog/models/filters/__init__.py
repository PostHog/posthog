from typing import TypeAlias
from .filter import Filter
from .path_filter import PathFilter
from .retention_filter import RetentionFilter
from .stickiness_filter import StickinessFilter
from .session_recordings_filter import SessionRecordingsFilter
from .properties_timeline_filter import PropertiesTimelineFilter

__all__ = [
    "Filter",
    "PathFilter",
    "RetentionFilter",
    "StickinessFilter",
    "SessionRecordingsFilter",
    "PropertiesTimelineFilter",
    "AnyFilter",
]

AnyFilter: TypeAlias = (
    Filter | PathFilter | RetentionFilter | StickinessFilter | SessionRecordingsFilter | PropertiesTimelineFilter
)

AnyInsightFilter: TypeAlias = Filter | PathFilter | RetentionFilter | StickinessFilter

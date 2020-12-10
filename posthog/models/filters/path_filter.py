from datetime import datetime
from functools import cached_property
from typing import Any, Callable, Dict, Optional, Tuple, Union

from django.db.models.expressions import Value
from django.db.models.functions.datetime import TruncDay, TruncHour, TruncMinute, TruncMonth, TruncWeek, TruncYear
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import (
    AUTOCAPTURE_EVENT,
    CUSTOM_EVENT,
    DATE_TO,
    INTERVAL,
    PAGEVIEW_EVENT,
    PATH_TYPE,
    SCREEN_EVENT,
    START_POINT,
    STICKINESS_DAYS,
)
from posthog.models.filters.filter import DateMixin, IntervalMixin
from posthog.models.property import PropertyMixin
from posthog.models.team import Team
from posthog.utils import relative_date_parse


class PathTypeMixin:
    _data: Dict

    @cached_property
    def path_type(self) -> Optional[str]:
        return self._data.get(PATH_TYPE, None)


class StartPointMixin:
    _data: Dict

    @cached_property
    def start_point(self) -> Optional[str]:
        return self._data.get(START_POINT, None)


class PropTypeMixin(PathTypeMixin):
    @cached_property
    def prop_type(self) -> str:
        if self.path_type == SCREEN_EVENT:
            return "properties->> '$screen_name'"
        elif self.path_type == AUTOCAPTURE_EVENT:
            return "tag_name_source"
        elif self.path_type == CUSTOM_EVENT:
            return "event"
        else:
            return "properties->> '$current_url'"


class ComparatorMixin(PropTypeMixin):
    @cached_property
    def comparator(self) -> str:
        if self.path_type == SCREEN_EVENT:
            return "{} =".format(self.prop_type)
        elif self.path_type == AUTOCAPTURE_EVENT:
            return "group_id ="
        elif self.path_type == CUSTOM_EVENT:
            return "event ="
        else:
            return "{} =".format(self.prop_type)


class TargetEventMixin(PropTypeMixin):
    @cached_property
    def target_event(self) -> Tuple[Optional[str], Dict[str, str]]:
        if self.path_type == SCREEN_EVENT:
            return SCREEN_EVENT, {"event": SCREEN_EVENT}
        elif self.path_type == AUTOCAPTURE_EVENT:
            return AUTOCAPTURE_EVENT, {"event": AUTOCAPTURE_EVENT}
        elif self.path_type == CUSTOM_EVENT:
            return None, {}
        else:
            return PAGEVIEW_EVENT, {"event": PAGEVIEW_EVENT}


class PathFilter(
    StartPointMixin, TargetEventMixin, ComparatorMixin, PropTypeMixin, DateMixin, PropertyMixin, IntervalMixin
):
    _data: Dict

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if request:
            data = {
                **request.GET.dict(),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._data = data

from functools import cached_property
from typing import Dict, Optional, Tuple

from posthog.constants import AUTOCAPTURE_EVENT, CUSTOM_EVENT, PAGEVIEW_EVENT, PATH_TYPE, SCREEN_EVENT, START_POINT
from posthog.models.filters.mixins.common import BaseParamMixin


class PathTypeMixin(BaseParamMixin):
    @cached_property
    def path_type(self) -> Optional[str]:
        return self._data.get(PATH_TYPE, None)


class StartPointMixin(BaseParamMixin):
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

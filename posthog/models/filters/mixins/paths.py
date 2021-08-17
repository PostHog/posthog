from typing import Dict, Literal, Optional, Tuple, cast

from posthog.constants import AUTOCAPTURE_EVENT, CUSTOM_EVENT, PAGEVIEW_EVENT, PATH_TYPE, SCREEN_EVENT, START_POINT
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict

PathType = Literal["$pageview", "$autocapture", "$screen", "custom_event"]


class PathTypeMixin(BaseParamMixin):
    @cached_property
    def path_type(self) -> Optional[PathType]:
        return self._data.get(PATH_TYPE, None)

    @include_dict
    def path_type_to_dict(self):
        return {"path_type": self.path_type} if self.path_type else {}


class StartPointMixin(BaseParamMixin):
    @cached_property
    def start_point(self) -> Optional[str]:
        return self._data.get(START_POINT, None)

    @include_dict
    def start_point_to_dict(self):
        return {"start_point": self.start_point} if self.start_point else {}


class PropTypeDerivedMixin(PathTypeMixin):
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


class ComparatorDerivedMixin(PropTypeDerivedMixin):
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


class TargetEventDerivedMixin(PropTypeDerivedMixin):
    @cached_property
    def target_event(self) -> Tuple[Optional[PathType], Dict[str, str]]:
        if self.path_type == SCREEN_EVENT:
            return cast(PathType, SCREEN_EVENT), {"event": SCREEN_EVENT}
        elif self.path_type == AUTOCAPTURE_EVENT:
            return cast(PathType, AUTOCAPTURE_EVENT), {"event": AUTOCAPTURE_EVENT}
        elif self.path_type == CUSTOM_EVENT:
            return None, {}
        else:
            return cast(PathType, PAGEVIEW_EVENT), {"event": PAGEVIEW_EVENT}

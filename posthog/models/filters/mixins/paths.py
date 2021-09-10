from typing import Dict, List, Literal, Optional, Tuple, cast

from posthog.constants import (
    CUSTOM_EVENT,
    END_POINT,
    FUNNEL_PATHS,
    PAGEVIEW_EVENT,
    PATH_TYPE,
    PATHS_EXCLUDE_EVENTS,
    PATHS_INCLUDE_CUSTOM_EVENTS,
    PATHS_INCLUDE_EVENT_TYPES,
    SCREEN_EVENT,
    START_POINT,
    STEP_LIMIT,
)
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict, process_bool

PathType = Literal["$pageview", "$screen", "custom_event"]

FunnelPathsType = Literal["funnel_path_before_step", "funnel_path_between_steps", "funnel_path_after_step"]


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


class EndPointMixin(BaseParamMixin):
    @cached_property
    def end_point(self) -> Optional[str]:
        return self._data.get(END_POINT, None)

    @include_dict
    def end_point_to_dict(self):
        return {"end_point": self.end_point} if self.end_point else {}


class PropTypeDerivedMixin(PathTypeMixin):
    @cached_property
    def prop_type(self) -> str:
        if self.path_type == SCREEN_EVENT:
            return "properties->> '$screen_name'"
        elif self.path_type == CUSTOM_EVENT:
            return "event"
        else:
            return "properties->> '$current_url'"


class ComparatorDerivedMixin(PropTypeDerivedMixin):
    @cached_property
    def comparator(self) -> str:
        if self.path_type == SCREEN_EVENT:
            return "{} =".format(self.prop_type)
        elif self.path_type == CUSTOM_EVENT:
            return "event ="
        else:
            return "{} =".format(self.prop_type)


class TargetEventDerivedMixin(PropTypeDerivedMixin):
    @cached_property
    def target_event(self) -> Tuple[Optional[PathType], Dict[str, str]]:
        if self.path_type == SCREEN_EVENT:
            return cast(PathType, SCREEN_EVENT), {"event": SCREEN_EVENT}
        elif self.path_type == CUSTOM_EVENT:
            return None, {}
        else:
            return cast(PathType, PAGEVIEW_EVENT), {"event": PAGEVIEW_EVENT}


class TargetEventsMixin(BaseParamMixin):
    @cached_property
    def target_events(self) -> List[str]:
        return self._data.get(PATHS_INCLUDE_EVENT_TYPES, [])

    @cached_property
    def custom_events(self) -> List[str]:
        return self._data.get(PATHS_INCLUDE_CUSTOM_EVENTS, [])

    @cached_property
    def exclude_events(self) -> List[str]:
        return self._data.get(PATHS_EXCLUDE_EVENTS, [])

    @property
    def include_pageviews(self) -> bool:
        return PAGEVIEW_EVENT in self.target_events

    @property
    def include_screenviews(self) -> bool:
        return SCREEN_EVENT in self.target_events

    @property
    def include_all_custom_events(self) -> bool:
        return CUSTOM_EVENT in self.target_events

    @include_dict
    def target_events_to_dict(self) -> dict:
        result = {}
        if self.target_events:
            result["target_events"] = self.target_events

        if self.custom_events:
            result["custom_events"] = self.custom_events

        if self.exclude_events:
            result["exclude_events"] = self.exclude_events
        return result


class PathStepLimitMixin(BaseParamMixin):
    @cached_property
    def step_limit(self) -> Optional[str]:
        return self._data.get(STEP_LIMIT, None)

    @include_dict
    def step_limit_to_dict(self):
        return {"step_limit": self.step_limit} if self.step_limit else {}


class FunnelPathsMixin(BaseParamMixin):
    @cached_property
    def funnel_paths(self) -> Optional[FunnelPathsType]:
        _funnel_paths = self._data.get(FUNNEL_PATHS, None)
        return _funnel_paths

    @include_dict
    def funnel_paths_to_dict(self):
        return {"funnel_paths": self.funnel_paths} if self.funnel_paths else {}

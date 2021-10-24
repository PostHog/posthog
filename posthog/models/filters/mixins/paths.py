import json
from typing import Dict, List, Literal, Optional, Tuple, cast

from posthog.constants import (
    CUSTOM_EVENT,
    END_POINT,
    FUNNEL_PATHS,
    LOCAL_PATH_CLEANING_FILTERS,
    PAGEVIEW_EVENT,
    PATH_DROPOFF_KEY,
    PATH_EDGE_LIMIT,
    PATH_END_KEY,
    PATH_GROUPINGS,
    PATH_MAX_EDGE_WEIGHT,
    PATH_MIN_EDGE_WEIGHT,
    PATH_REPLACEMENTS,
    PATH_START_KEY,
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
        target_events = self._data.get(PATHS_INCLUDE_EVENT_TYPES, [])
        if isinstance(target_events, str):
            return json.loads(target_events)
        return target_events

    @cached_property
    def custom_events(self) -> List[str]:
        custom_events = self._data.get(PATHS_INCLUDE_CUSTOM_EVENTS, [])
        if isinstance(custom_events, str):
            return json.loads(custom_events)
        return custom_events

    @cached_property
    def exclude_events(self) -> List[str]:
        _exclude_events = self._data.get(PATHS_EXCLUDE_EVENTS, [])
        if isinstance(_exclude_events, str):
            return json.loads(_exclude_events)

        return _exclude_events

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
    def step_limit(self) -> Optional[int]:
        if self._data.get(STEP_LIMIT) is not None:
            return int(self._data[STEP_LIMIT])
        return None

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


class PathGroupingMixin(BaseParamMixin):
    @cached_property
    def path_groupings(self) -> Optional[List[str]]:
        path_groupings = self._data.get(PATH_GROUPINGS, None)
        if isinstance(path_groupings, str):
            return json.loads(path_groupings)

        return path_groupings

    @include_dict
    def path_groupings_to_dict(self):
        return {PATH_GROUPINGS: self.path_groupings} if self.path_groupings else {}


class PathReplacementMixin(BaseParamMixin):
    @cached_property
    def path_replacements(self) -> bool:
        path_replacements = self._data.get(PATH_REPLACEMENTS)
        if not path_replacements:
            return False
        if path_replacements == True:
            return True

        if isinstance(path_replacements, str) and path_replacements.lower() == "true":
            return True

        return False

    @include_dict
    def path_replacements_to_dict(self):
        return {PATH_REPLACEMENTS: self.path_replacements} if self.path_replacements else {}


class LocalPathCleaningFiltersMixin(BaseParamMixin):
    @cached_property
    def local_path_cleaning_filters(self) -> Optional[List[Dict[str, str]]]:
        local_path_cleaning_filters = self._data.get(LOCAL_PATH_CLEANING_FILTERS, None)
        if isinstance(local_path_cleaning_filters, str):
            return json.loads(local_path_cleaning_filters)

        return local_path_cleaning_filters

    @include_dict
    def local_path_cleaning_filters_to_dict(self):
        return (
            {LOCAL_PATH_CLEANING_FILTERS: self.local_path_cleaning_filters} if self.local_path_cleaning_filters else {}
        )


class PathPersonsMixin(BaseParamMixin):
    @cached_property
    def path_start_key(self) -> Optional[str]:
        return self._data.get(PATH_START_KEY)

    @cached_property
    def path_end_key(self) -> Optional[str]:
        return self._data.get(PATH_END_KEY)

    @cached_property
    def path_dropoff_key(self) -> Optional[str]:
        return self._data.get(PATH_DROPOFF_KEY)

    @include_dict
    def path_start_end_to_dict(self):
        result = {}
        if self.path_start_key:
            result[PATH_START_KEY] = self.path_start_key

        if self.path_end_key:
            result[PATH_END_KEY] = self.path_end_key

        if self.path_dropoff_key:
            result[PATH_DROPOFF_KEY] = self.path_dropoff_key

        return result


class PathLimitsMixin(BaseParamMixin):
    @cached_property
    def edge_limit(self) -> Optional[int]:
        raw_value = self._data.get(PATH_EDGE_LIMIT, None)
        return int(raw_value) if raw_value is not None else None

    @cached_property
    def min_edge_weight(self) -> Optional[int]:
        raw_value = self._data.get(PATH_MIN_EDGE_WEIGHT, None)
        return int(raw_value) if raw_value else None

    @cached_property
    def max_edge_weight(self) -> Optional[int]:
        raw_value = self._data.get(PATH_MAX_EDGE_WEIGHT, None)
        return int(raw_value) if raw_value else None

    @include_dict
    def path_edge_limit_to_dict(self):
        result = {}
        if self.edge_limit:
            result[PATH_EDGE_LIMIT] = self.edge_limit

        if self.min_edge_weight:
            result[PATH_MIN_EDGE_WEIGHT] = self.min_edge_weight

        if self.max_edge_weight:
            result[PATH_MAX_EDGE_WEIGHT] = self.max_edge_weight

        return result

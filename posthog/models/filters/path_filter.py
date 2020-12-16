import json
from datetime import datetime
from typing import Any, Dict

from posthog.models.entity import Entity
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import DateMixin, IntervalMixin
from posthog.models.filters.mixins.paths import (
    ComparatorDerivedMixin,
    PropTypeDerivedMixin,
    StartPointMixin,
    TargetEventDerivedMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.property import Property


class PathFilter(
    StartPointMixin,
    TargetEventDerivedMixin,
    ComparatorDerivedMixin,
    PropTypeDerivedMixin,
    DateMixin,
    PropertyMixin,
    IntervalMixin,
    BaseFilter,
):
    def to_dict(self) -> Dict[str, Any]:
        ret = {}

        for key in dir(self):
            value = getattr(self, key)
            if key in [
                "entities",
                "determine_time_delta",
                "date_filter_Q",
                "custom_date_filter_Q",
                "properties_to_Q",
                "toJSON",
                "to_dict",
            ] or key.startswith("_"):
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if not isinstance(value, list) and not value:
                continue
            if key == "date_from" and not self._date_from:
                continue
            if key == "date_to" and not self._date_to:
                continue
            if isinstance(value, datetime):
                value = value.isoformat()
            if not isinstance(value, (list, bool, int, float, str)):
                # Try to see if this object is json serializable
                try:
                    json.dumps(value)
                except:
                    continue
            if isinstance(value, Entity):
                value = value.to_dict()
            if key == "properties" and isinstance(value, list) and isinstance(value[0], Property):
                value = [prop.to_dict() for prop in value]
            if isinstance(value, list) and isinstance(value[0], Entity):
                value = [entity.to_dict() for entity in value]
            ret[key] = value

        return ret

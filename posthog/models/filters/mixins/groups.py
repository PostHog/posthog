from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from posthog.constants import AGGREGATION_GROUP_TYPE_INDEX, GROUP_TYPES_LIMIT
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict


def validate_group_type_index(param_name: str, value: Any, required=False) -> Optional[int]:
    error = ValidationError(
        f"{param_name} is required to be greater than 0 and less than {GROUP_TYPES_LIMIT}", code="invalid"
    )

    if required and value is None:
        raise error

    if value is not None:
        value = int(value)
        if not (0 <= value < GROUP_TYPES_LIMIT):
            raise error

    return value


class GroupsAggregationMixin(BaseParamMixin):
    @cached_property
    def aggregation_group_type_index(self) -> Optional[int]:
        value = self._data.get(AGGREGATION_GROUP_TYPE_INDEX)
        value = validate_group_type_index(AGGREGATION_GROUP_TYPE_INDEX, value)

        return value

    @include_dict
    def aggregation_group_type_index_to_dict(self):
        return (
            {AGGREGATION_GROUP_TYPE_INDEX: self.aggregation_group_type_index}
            if self.aggregation_group_type_index is not None
            else {}
        )

from typing import Optional

from posthog.constants import AGGREGATION_GROUP_TYPE_INDEX
from posthog.models.filters.mixins.common import BaseParamMixin
from posthog.models.filters.mixins.utils import cached_property, include_dict
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index


class GroupsAggregationMixin(BaseParamMixin):
    @cached_property
    def aggregation_group_type_index(self) -> Optional[GroupTypeIndex]:
        value = self._data.get(AGGREGATION_GROUP_TYPE_INDEX)
        return validate_group_type_index(AGGREGATION_GROUP_TYPE_INDEX, value)

    @include_dict
    def aggregation_group_type_index_to_dict(self):
        return (
            {AGGREGATION_GROUP_TYPE_INDEX: self.aggregation_group_type_index}
            if self.aggregation_group_type_index is not None
            else {}
        )

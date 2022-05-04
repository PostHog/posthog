from typing import Counter, List, Set, cast

from ee.clickhouse.models.property import box_value, extract_tables_and_properties
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, FunnelCorrelationType
from posthog.models.action.util import get_action_tables_and_properties
from posthog.models.entity import Entity
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.property import PropertyIdentifier
from posthog.queries.column_optimizer import ColumnOptimizer


class EnterpriseColumnOptimizer(ColumnOptimizer):
    @cached_property
    def group_types_to_query(self) -> Set[GroupTypeIndex]:
        used_properties = self._used_properties_with_type("group")
        return set(cast(GroupTypeIndex, group_type_index) for _, _, group_type_index in used_properties)

    @cached_property
    def properties_used_in_filter(self) -> Counter[PropertyIdentifier]:
        "Returns collection of properties + types that this query would use"
        counter: Counter[PropertyIdentifier] = extract_tables_and_properties(self.filter.property_groups.flat)

        if not isinstance(self.filter, StickinessFilter):
            # Some breakdown types read properties
            #
            # See ee/clickhouse/queries/trends/breakdown.py#get_query or
            # ee/clickhouse/queries/breakdown_props.py#get_breakdown_prop_values
            if self.filter.breakdown_type in ["event", "person"]:
                boxed_breakdown = box_value(self.filter.breakdown)
                for b in boxed_breakdown:
                    if isinstance(b, str):
                        counter[(b, self.filter.breakdown_type, self.filter.breakdown_group_type_index)] += 1
            elif self.filter.breakdown_type == "group":
                # :TRICKY: We only support string breakdown for group properties
                assert isinstance(self.filter.breakdown, str)
                counter[
                    (self.filter.breakdown, self.filter.breakdown_type, self.filter.breakdown_group_type_index)
                ] += 1

            # If we have a breakdowns attribute then make sure we pull in everything we
            # need to calculate it
            for breakdown in self.filter.breakdowns or []:
                counter[(breakdown["property"], breakdown["type"], self.filter.breakdown_group_type_index)] += 1

        # Both entities and funnel exclusions can contain nested property filters
        for entity in self.filter.entities + cast(List[Entity], self.filter.exclusions):
            counter += extract_tables_and_properties(entity.property_groups.flat)

            # Math properties are also implicitly used.
            #
            # See ee/clickhouse/queries/trends/util.py#process_math
            if entity.math_property:
                counter[(entity.math_property, "event", None)] += 1

            # If groups are involved, they're also used
            #
            # See ee/clickhouse/queries/trends/util.py#process_math
            if entity.math == "unique_group":
                counter[(f"$group_{entity.math_group_type_index}", "event", None)] += 1

            # :TRICKY: If action contains property filters, these need to be included
            #
            # See ee/clickhouse/models/action.py#format_action_filter for an example
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                counter += get_action_tables_and_properties(entity.get_action())

        if (
            not isinstance(self.filter, StickinessFilter)
            and self.filter.correlation_type == FunnelCorrelationType.PROPERTIES
            and self.filter.correlation_property_names
        ):

            if self.filter.aggregation_group_type_index is not None:
                for prop_value in self.filter.correlation_property_names:
                    counter[(prop_value, "group", self.filter.aggregation_group_type_index)] += 1
            else:
                for prop_value in self.filter.correlation_property_names:
                    counter[(prop_value, "person", None)] += 1

        return counter

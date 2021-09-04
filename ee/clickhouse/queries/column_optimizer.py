from typing import List, Set, Tuple, Union, cast

from ee.clickhouse.materialized_columns.columns import ColumnName, get_materialized_columns
from ee.clickhouse.models.action import get_action_tables_and_properties, uses_elements_chain
from ee.clickhouse.models.property import extract_tables_and_properties
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property import Property, PropertyName, PropertyType
from posthog.models.team import Team


class ColumnOptimizer:
    """
    This class is responsible for figuring out what columns can and should be materialized based on the query filter.

    This speeds up queries since clickhouse ends up selecting less data.
    """

    def __init__(self, filter: Union[Filter, PathFilter], team_id: int):
        self.filter = filter
        self.team_id = team_id

    @cached_property
    def materialized_event_columns_to_query(self) -> List[ColumnName]:
        "Returns a list of event table columns containing materialized properties that this query needs"

        materialized_columns = get_materialized_columns("events")
        return [
            materialized_columns[property_name]
            for property_name, type in self._used_properties_with_type("event")
            if property_name in materialized_columns
        ]

    @cached_property
    def materialized_person_columns_to_query(self) -> List[ColumnName]:
        "Returns a list of person table columns containing materialized properties that this query needs"

        materialized_columns = get_materialized_columns("person")
        return [
            materialized_columns[property_name]
            for property_name, type in self._used_properties_with_type("person")
            if property_name in materialized_columns
        ]

    @cached_property
    def should_query_event_properties_column(self) -> bool:
        return len(self.materialized_event_columns_to_query) != len(self._used_properties_with_type("event"))

    @cached_property
    def should_query_person_properties_column(self) -> bool:
        return len(self.materialized_person_columns_to_query) != len(self._used_properties_with_type("person"))

    @cached_property
    def should_query_elements_chain_column(self) -> bool:
        "Returns whether this query uses elements_chain"
        has_element_type_property = lambda properties: any(prop.type == "element" for prop in properties)

        if has_element_type_property(self.filter.properties):
            return True

        if self.filter.filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=self.team_id).test_account_filters
            properties = [Property(**prop) for prop in test_account_filters]
            if has_element_type_property(properties):
                return True

        # Both entities and funnel exclusions can contain nested elements_chain inclusions
        for entity in self.filter.entities + cast(List[Entity], self.filter.exclusions):
            if has_element_type_property(entity.properties):
                return True

            # :TRICKY: Action definition may contain elements_chain usage
            #
            # See ee/clickhouse/models/action.py#format_action_filter for an example
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                if uses_elements_chain(entity.get_action()):
                    return True

        return False

    @cached_property
    def properties_used_in_filter(self) -> Set[Tuple[PropertyName, PropertyType]]:
        "Returns list of properties + types that this query would use"
        result: Set[Tuple[PropertyName, PropertyType]] = set()

        result |= extract_tables_and_properties(self.filter.properties)
        if self.filter.filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=self.team_id).test_account_filters
            result |= extract_tables_and_properties([Property(**prop) for prop in test_account_filters])

        # Some breakdown types read properties
        #
        # See ee/clickhouse/queries/trends/breakdown.py#get_query or
        # ee/clickhouse/queries/breakdown_props.py#get_breakdown_event_prop_values
        if self.filter.breakdown_type in ["event", "person"]:
            # :TRICKY: We only support string breakdown for event/person properties
            assert isinstance(self.filter.breakdown, str)
            result.add((self.filter.breakdown, self.filter.breakdown_type))

        # Both entities and funnel exclusions can contain nested property filters
        for entity in self.filter.entities + cast(List[Entity], self.filter.exclusions):
            result |= extract_tables_and_properties(entity.properties)

            # Math properties are also implicitly used.
            #
            # See ee/clickhouse/queries/trends/util.py#process_math
            if entity.math_property:
                result.add((entity.math_property, "event"))

            # :TRICKY: If action contains property filters, these need to be included
            #
            # See ee/clickhouse/models/action.py#format_action_filter for an example
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                result |= get_action_tables_and_properties(entity.get_action())

        return result

    def _used_properties_with_type(self, property_type: PropertyType) -> Set[Tuple[PropertyName, PropertyType]]:
        return set((name, type) for name, type in self.properties_used_in_filter if type == property_type)

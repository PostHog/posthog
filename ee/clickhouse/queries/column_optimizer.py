from typing import List, Set

from ee.clickhouse.materialized_columns import get_materialized_columns
from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.action import get_action_tables_and_properties
from ee.clickhouse.models.property import TableAndProperty, extract_tables_and_properties
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import Property
from posthog.models.team import Team


class ColumnOptimizer:
    """
    This class is responsible for figuring out what columns can and should be materialized based on the query filter.

    This speeds up queries since clickhouse ends up selecting less data.
    """

    def __init__(self, filter: Filter, team_id: int):
        self.filter = filter
        self.team_id = team_id

    @cached_property
    def event_columns_to_query(self) -> List[ColumnName]:
        materialized_columns = get_materialized_columns("events")
        return [
            materialized_columns[property_name]
            for table, property_name in self.properties_used_in_filter
            if table == "events" and property_name in materialized_columns
        ]

    @cached_property
    def should_query_event_properties_column(self) -> bool:
        return len(self.event_columns_to_query) != len(self.properties_used_in_filter)

    @cached_property
    def properties_used_in_filter(self) -> Set[TableAndProperty]:
        result: Set[TableAndProperty] = set()

        result.extend(extract_tables_and_properties(self._filter.properties))
        if self._filter.filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=self.team_id).test_account_filters
            result.extend(extract_tables_and_properties([Property(**prop) for prop in test_account_filters]))

        if self._filter.breakdown_type == "person":
            result.add(("person", self._filter.breakdown))
        elif self._filter.breakdown_type == "event":
            result.add(("events", self._filter.breakdown))

        for entity in self._filter.entities:
            result.extend(extract_tables_and_properties(entity.properties))

            if entity.math_property:
                result.add(("events", entity.math_property))

            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                result.extend(get_action_tables_and_properties(entity.get_action()))

        return result

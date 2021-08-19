from typing import Any, Dict, Tuple

from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from posthog.models.property import Property
from posthog.models.team import Team


class PathEventQuery(ClickhouseEventQuery):
    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.timestamp AS timestamp, if({self.EVENT_TABLE_ALIAS}.event = '$pageview', JSONExtractString({self.EVENT_TABLE_ALIAS}.properties, '$current_url'), if({self.EVENT_TABLE_ALIAS}.event = '$autocapture', concat('autocapture:', {self.EVENT_TABLE_ALIAS}.elements_chain), {self.EVENT_TABLE_ALIAS}.event)) AS path_item"
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
        )

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_filters = self._filter.properties
        prop_query, prop_params = self._get_props(prop_filters, allow_denormalized_props=True)
        self.params.update(prop_params)

        query = f"""
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_disintct_id_query()}
            {self._get_person_query()}
            WHERE team_id = %(team_id)s
            AND (event = '$pageview' OR event = '$autocapture' OR NOT event LIKE %(custom_event_match)s)
            {date_query}
            {prop_query}
            ORDER BY {self.DISTINCT_ID_TABLE_ALIAS}.person_id, {self.EVENT_TABLE_ALIAS}.timestamp
        """
        self.params.update({"custom_event_match": "$%"})
        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        if any(self._should_property_join_persons(prop) for prop in self._filter.properties):
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

        if self._filter.filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=self._team_id).test_account_filters
            test_filter_props = [Property(**prop) for prop in test_account_filters]
            if any(self._should_property_join_persons(prop) for prop in test_filter_props):
                self._should_join_distinct_ids = True
                self._should_join_persons = True
                return

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query


class TestSeriesValuesPreaggregatedTable(BaseTest):
    def test_a_project_with_property_access_rules_cannot_read_the_table(self) -> None:
        with patch("products.access_control.backend.facade.api.team_has_property_access_rules", return_value=True):
            with self.assertRaises(QueryError):
                execute_hogql_query("SELECT count() FROM posthog.series_values_preaggregated", team=self.team)

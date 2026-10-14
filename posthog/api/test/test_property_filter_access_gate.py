from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.api.property_filter_access_gate import table_blocking_property_filters
from posthog.test.warehouse_access import WAREHOUSE_ACCESS_CONTROL_FLAG, deny_warehouse_table_to_member


class TestTableBlockingPropertyFilters(APIBaseTest):
    @parameterized.expand(
        [
            ("subquery", "distinct_id IN (SELECT id FROM denied_warehouse_table)", "denied_warehouse_table"),
            ("aliased_subquery", "e.distinct_id IN (SELECT id FROM denied_warehouse_table)", "denied_warehouse_table"),
            ("aliased_join", "e.person.denied_join.id = 'internal'", "denied_warehouse_table"),
            ("aliased_allowed", "e.distinct_id = 'internal'", None),
        ]
    )
    @patch(WAREHOUSE_ACCESS_CONTROL_FLAG, return_value=True)
    def test_sql_filter_names_denied_table(self, _name: str, key: str, expected: str | None, _flag):
        deny_warehouse_table_to_member(self.organization, self.team, self.user)

        assert table_blocking_property_filters(self.user, self.team, [{"type": "hogql", "key": key}]) == expected

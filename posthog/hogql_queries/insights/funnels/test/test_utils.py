from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import ActionsNode, DataWarehouseNode, EventsNode

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clone_expr

from posthog.hogql_queries.insights.funnels.utils import alias_columns_in_select, entity_config_mismatch


def _data_warehouse_node(**overrides) -> DataWarehouseNode:
    node_data: dict[str, str] = {
        "id": "payments",
        "table_name": "payments",
        "id_field": "id",
        "distinct_id_field": "person_id",
        "timestamp_field": "created_at",
    }
    node_data.update(overrides)
    return DataWarehouseNode(**node_data)


class TestUtils(SimpleTestCase):
    def test_alias_columns_in_select(self):
        sql = """
        SELECT
            e.timestamp AS timestamp,
            person_id AS aggregation_target,
            if(event = '$pageview' and properties.$browser = 'Opera', 1, 0) AS step_0,
            0 as step_1
        """
        query = parse_select(sql)
        assert isinstance(query, ast.SelectQuery)

        result = alias_columns_in_select(query.select, table_alias="my_table")
        result = [clone_expr(r, clear_locations=True) for r in result]  # remove locations from ast for easier asserts

        assert len(result) == 4
        assert result[0] == ast.Alias(alias="timestamp", expr=ast.Field(chain=["my_table", "timestamp"]))
        assert result[1] == ast.Alias(
            alias="aggregation_target", expr=ast.Field(chain=["my_table", "aggregation_target"])
        )
        assert result[2] == ast.Alias(alias="step_0", expr=ast.Field(chain=["my_table", "step_0"]))
        assert result[3] == ast.Alias(alias="step_1", expr=ast.Field(chain=["my_table", "step_1"]))

    @parameterized.expand(
        [
            ("events_vs_events", EventsNode(event="$pageview"), EventsNode(event="$signup"), False),
            ("events_vs_actions", EventsNode(event="$pageview"), ActionsNode(id=1), False),
            ("events_vs_none", EventsNode(event="$pageview"), None, False),
            ("events_vs_dwh", EventsNode(event="$pageview"), _data_warehouse_node(), True),
            ("dwh_vs_actions", _data_warehouse_node(), ActionsNode(id=1), True),
            ("dwh_vs_none", _data_warehouse_node(), None, True),
            ("dwh_vs_events", _data_warehouse_node(), EventsNode(event="$pageview"), True),
        ]
    )
    def test_entity_config_mismatch_for_entity_types(
        self, _name: str, step_entity, table_entity, expected_mismatch: bool
    ) -> None:
        assert entity_config_mismatch(step_entity, table_entity) is expected_mismatch

    @parameterized.expand(
        [
            ("same_config", {}, {}, False),
            ("different_id_field", {}, {"id_field": "other_id"}, True),
            ("different_distinct_id_field", {}, {"distinct_id_field": "other_distinct_id"}, True),
            ("different_timestamp_field", {}, {"timestamp_field": "other_timestamp"}, True),
        ]
    )
    def test_entity_config_mismatch_for_dwh_config_keys(
        self,
        _name: str,
        step_overrides: dict[str, str],
        table_overrides: dict[str, str],
        expected_mismatch: bool,
    ) -> None:
        step_entity = _data_warehouse_node(**step_overrides)
        table_entity = _data_warehouse_node(**table_overrides)

        assert entity_config_mismatch(step_entity, table_entity) is expected_mismatch

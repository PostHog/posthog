from textwrap import dedent

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

import regex
import sqlparse

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    FunnelsQuery,
    GroupNode,
)

from posthog.hogql import ast

from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.models.action.action import Action

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseTable


def format_query(query: ast.SelectQuery):
    sql = str(query)[4:-1]
    return sqlparse.format(sql, keyword_case="upper", reindent=True)


class TestFunnelEventQuery(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.warehouse_credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="key", access_secret="secret"
        )
        self._create_data_warehouse_table(
            name="payments",
            id_field="id",
            distinct_id_field="user_id",
            timestamp_field="created_at",
        )
        self._create_data_warehouse_table(
            name="payments_string_timestamp",
            id_field="id",
            distinct_id_field="user_id",
            timestamp_field="created_at_str",
            timestamp_column={
                "hogql": "StringDatabaseField",
                "clickhouse": "String",
                "valid": True,
            },
        )
        self._create_data_warehouse_table(
            name="table_one",
            id_field="id",
            distinct_id_field="user_id",
            timestamp_field="created_at",
            extra_columns={
                "some_prop": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
                "other_prop": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
        )
        self._create_data_warehouse_table(
            name="table_two",
            id_field="some_id",
            distinct_id_field="some_user_id",
            timestamp_field="ts",
            extra_columns={
                "another_prop": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
        )

    def _create_data_warehouse_table(
        self,
        name: str,
        id_field: str,
        distinct_id_field: str,
        timestamp_field: str,
        extra_columns: dict[str, dict[str, str | bool]] | None = None,
        timestamp_column: dict[str, str | bool] | None = None,
    ) -> None:
        columns: dict[str, dict[str, str | bool]] = {
            id_field: {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            distinct_id_field: {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            timestamp_field: timestamp_column
            or {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime64(3, 'UTC')", "valid": True},
        }
        if extra_columns:
            columns.update(extra_columns)

        DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            format=DataWarehouseTable.TableFormat.CSV,
            url_pattern="http://localhost/file.csv",
            credential=self.warehouse_credential,
            columns=columns,
        )

    @freeze_time("2025-11-12")
    def test_single_events_table(self):
        query = FunnelsQuery(series=[EventsNode(), EventsNode()])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(1, 1, 0) AS step_0,
                   if(1, 1, 0) AS step_1
            FROM EVENTS AS e
            WHERE and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), or(equals(step_0, 1), equals(step_1, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_single_dwh_table(self):
        dwh_node = DataWarehouseNode(
            distinct_id_field="user_id",
            timestamp_field="created_at",
            table_name="payments",
            id="payments",
            id_field="id",
        )
        query = FunnelsQuery(series=[dwh_node, dwh_node])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT e.created_at AS timestamp,
                   user_id AS aggregation_target,
                   if(1, 1, 0) AS step_0,
                   if(1, 1, 0) AS step_1
            FROM payments AS e
            WHERE and(and(greaterOrEquals(timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(timestamp, toDateTime('2025-11-12 23:59:59.999999'))), or(equals(step_0, 1), equals(step_1, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_single_dwh_table_string_timestamp(self):
        dwh_node = DataWarehouseNode(
            distinct_id_field="user_id",
            timestamp_field="created_at_str",
            table_name="payments_string_timestamp",
            id="payments_string_timestamp",
            id_field="id",
        )
        query = FunnelsQuery(series=[dwh_node, dwh_node])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT toDateTime(e.created_at_str) AS timestamp,
                   user_id AS aggregation_target,
                   if(1, 1, 0) AS step_0,
                   if(1, 1, 0) AS step_1
            FROM payments_string_timestamp AS e
            WHERE and(and(greaterOrEquals(timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(timestamp, toDateTime('2025-11-12 23:59:59.999999'))), or(equals(step_0, 1), equals(step_1, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_multiple_tables(self):
        query = FunnelsQuery(
            kind="FunnelsQuery",
            series=[
                EventsNode(
                    event="$pageview",
                    properties=[EventPropertyFilter(key="$browser", value=["Opera"], operator="exact")],
                ),
                DataWarehouseNode(
                    id="table_one",
                    table_name="table_one",
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created_at",
                    properties=[DataWarehousePropertyFilter(key="some_prop", value="some_value", operator="exact")],
                ),
                DataWarehouseNode(
                    id="table_two",
                    table_name="table_two",
                    id_field="some_id",
                    distinct_id_field="some_user_id",
                    timestamp_field="ts",
                    properties=[
                        DataWarehousePropertyFilter(key="another_prop", value="another_value", operator="exact")
                    ],
                ),
                DataWarehouseNode(
                    id="table_one",
                    table_name="table_one",
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created_at",
                    properties=[DataWarehousePropertyFilter(key="other_prop", value="other_value", operator="exact")],
                ),
            ],
        )
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        select = regex.sub(
            r"\((?:[^()]+|(?R))*\)", "(...)", select, count=1
        )  # replace everything in the first parenthesis to get the outer query
        expected = dedent("""
            SELECT e.timestamp AS timestamp,
                   e.aggregation_target AS aggregation_target,
                   e.step_0 AS step_0,
                   e.step_1 AS step_1,
                   e.step_2 AS step_2,
                   e.step_3 AS step_3
            FROM
              (...) AS e
        """).strip()
        self.assertEqual(select, expected)

        select_1 = format_query(funnel_event_query.select_from.table.initial_select_query)  # type: ignore
        expected_1 = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(and(equals(event, '$pageview'), equals(properties.$browser, 'Opera')), 1, 0) AS step_0,
                   0 AS step_1,
                   0 AS step_2,
                   0 AS step_3
            FROM EVENTS AS e
            WHERE and(and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), IN(event, tuple('$pageview'))), equals(step_0, 1))
        """).strip()
        self.assertEqual(select_1, expected_1)

        select_2 = format_query(funnel_event_query.select_from.table.subsequent_select_queries[0].select_query)  # type: ignore
        expected_2 = dedent("""
            SELECT e.created_at AS timestamp,
                   user_id AS aggregation_target,
                   0 AS step_0,
                   if(and(1, equals(some_prop, 'some_value')), 1, 0) AS step_1,
                   0 AS step_2,
                   if(and(1, equals(other_prop, 'other_value')), 1, 0) AS step_3
            FROM table_one AS e
            WHERE and(and(greaterOrEquals(timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(timestamp, toDateTime('2025-11-12 23:59:59.999999'))), or(equals(step_1, 1), equals(step_3, 1)))
        """).strip()
        self.assertEqual(select_2, expected_2)

        select_3 = format_query(funnel_event_query.select_from.table.subsequent_select_queries[1].select_query)  # type: ignore
        expected_3 = dedent("""
            SELECT e.ts AS timestamp,
                   some_user_id AS aggregation_target,
                   0 AS step_0,
                   0 AS step_1,
                   if(and(1, equals(another_prop, 'another_value')), 1, 0) AS step_2,
                   0 AS step_3
            FROM table_two AS e
            WHERE and(and(greaterOrEquals(timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(timestamp, toDateTime('2025-11-12 23:59:59.999999'))), equals(step_2, 1))
        """).strip()
        self.assertEqual(select_3, expected_3)

    @freeze_time("2025-11-12")
    def test_group_node_two_events(self):
        group = GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        )
        query = FunnelsQuery(series=[group, EventsNode(event="$checkout")])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(or(equals(event, '$pageview'), equals(event, '$pageleave')), 1, 0) AS step_0,
                   if(equals(event, '$checkout'), 1, 0) AS step_1
            FROM EVENTS AS e
            WHERE and(and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), IN(event, tuple('$checkout', '$pageleave', '$pageview'))), or(equals(step_0, 1), equals(step_1, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_group_node_between_event_and_action(self):
        checkout_action = Action.objects.create(
            team=self.team,
            name="Checkout Action",
            steps_json=[{"event": "checkout"}, {"event": "purchase"}],
        )
        group = GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        )
        query = FunnelsQuery(
            series=[
                EventsNode(event="sign up"),
                group,
                ActionsNode(id=checkout_action.id),
            ]
        )
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(equals(event, 'sign up'), 1, 0) AS step_0,
                   if(or(equals(event, '$pageview'), equals(event, '$pageleave')), 1, 0) AS step_1,
                   if(or(equals(event, 'checkout'), equals(event, 'purchase')), 1, 0) AS step_2
            FROM EVENTS AS e
            WHERE and(and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), IN(event, tuple('$pageleave', '$pageview', 'checkout', 'purchase', 'sign up'))), or(equals(step_0, 1), equals(step_1, 1), equals(step_2, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_group_node_with_property_filters(self):
        group = GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[
                EventsNode(
                    event="$pageview",
                    properties=[EventPropertyFilter(key="$browser", value="Chrome", operator="exact")],
                ),
                EventsNode(
                    event="$pageleave",
                    properties=[EventPropertyFilter(key="$browser", value="Firefox", operator="exact")],
                ),
            ],
        )
        query = FunnelsQuery(series=[group, EventsNode(event="$checkout")])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(or(and(equals(event, '$pageview'), equals(properties.$browser, 'Chrome')), and(equals(event, '$pageleave'), equals(properties.$browser, 'Firefox'))), 1, 0) AS step_0,
                   if(equals(event, '$checkout'), 1, 0) AS step_1
            FROM EVENTS AS e
            WHERE and(and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), IN(event, tuple('$checkout', '$pageleave', '$pageview'))), or(equals(step_0, 1), equals(step_1, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_group_node_event_or_action(self):
        action = Action.objects.create(
            team=self.team,
            name="Onboarding",
            steps_json=[{"event": "sign up"}, {"event": "onboarding completed"}],
        )
        group = GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[ActionsNode(id=action.id), EventsNode(event="$pageview")],
        )
        query = FunnelsQuery(series=[group, EventsNode(event="$checkout")])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        expected = dedent("""
            SELECT e.timestamp AS timestamp,
                   person_id AS aggregation_target,
                   if(or(or(equals(event, 'sign up'), equals(event, 'onboarding completed')), equals(event, '$pageview')), 1, 0) AS step_0,
                   if(equals(event, '$checkout'), 1, 0) AS step_1
            FROM EVENTS AS e
            WHERE and(and(and(greaterOrEquals(e.timestamp, toDateTime('2025-11-05 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2025-11-12 23:59:59.999999'))), IN(event, tuple('$checkout', '$pageview', 'onboarding completed', 'sign up'))), or(equals(step_0, 1), equals(step_1, 1)))
        """).strip()
        self.assertEqual(select, expected)

    @freeze_time("2025-11-12")
    def test_group_node_entity_prefilter(self):
        group = GroupNode(
            operator=FilterLogicalOperator.OR_,
            nodes=[EventsNode(event="$pageview"), EventsNode(event="$pageleave")],
        )
        query = FunnelsQuery(series=[group])
        context = FunnelQueryContext(query=query, team=self.team)

        funnel_event_query = FunnelEventQuery(context=context).to_query()

        select = format_query(funnel_event_query)
        self.assertIn("IN(event, tuple('$pageleave', '$pageview'))", select)

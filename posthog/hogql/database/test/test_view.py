from typing import Literal

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery, TableNode
from posthog.hogql.database.test.tables import (
    create_aapl_stock_s3_table,
    create_aapl_stock_table_self_referencing,
    create_aapl_stock_table_view,
    create_nested_aapl_stock_view,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team


class TestView(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()

        self.database = Database.create_for(team=self.team)
        self.database._add_views(
            TableNode(
                children={
                    "aapl_stock_view": TableNode(
                        name="aapl_stock_view",
                        table=create_aapl_stock_table_view(),
                    ),
                    "aapl_stock_nested_view": TableNode(
                        name="aapl_stock_nested_view",
                        table=create_nested_aapl_stock_view(),
                    ),
                }
            )
        )
        self.database._add_warehouse_tables(
            TableNode(
                children={
                    "aapl_stock": TableNode(
                        name="aapl_stock",
                        table=create_aapl_stock_s3_table(),
                    ),
                    "aapl_stock_self": TableNode(
                        name="aapl_stock_self",
                        table=create_aapl_stock_table_self_referencing(),
                    ),
                }
            )
        )

        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    @parameterized.expand(
        [
            ("warehouse_table", "aapl_stock_view", "warehouse_table"),
            ("self_managed_table", "aapl_stock_view", "self_managed_table"),
            ("self_managed_table", "events", "posthog_table"),
        ]
    )
    def test_a_view_shadowed_by_a_table_keeps_the_table_and_is_counted(
        self, added_as: str, name: str, shadowed_by: str
    ):
        database = Database.create_for(team=self.team)
        tables = TableNode(children={name: TableNode(name=name, table=create_aapl_stock_s3_table(name))})
        if added_as == "warehouse_table":
            database._add_warehouse_tables(tables)
        else:
            database._add_warehouse_self_managed_tables(tables)

        client = MagicMock()
        with patch("posthoganalytics.default_client", client):
            database._add_views(
                TableNode(
                    children={
                        name: TableNode(name=name, table=create_aapl_stock_table_view()),
                        "aapl_stock_nested_view": TableNode(
                            name="aapl_stock_nested_view", table=create_nested_aapl_stock_view()
                        ),
                    }
                )
            )

        assert not isinstance(database.get_table([name]), SavedQuery)
        client.metrics.count.assert_called_once_with(
            "hogql.database.views_shadowed", 1, attributes={"shadowed_by": shadowed_by}
        )

    def test_a_nested_view_is_not_shadowed_by_a_flat_table_with_the_same_dotted_name(self):
        database = Database.create_for(team=self.team)
        database._add_warehouse_self_managed_tables(
            TableNode(
                children={
                    "schema.stock": TableNode(name="schema.stock", table=create_aapl_stock_s3_table("schema.stock"))
                }
            )
        )

        client = MagicMock()
        with patch("posthoganalytics.default_client", client):
            database._add_views(
                TableNode(
                    children={
                        "schema": TableNode.create_nested_for_chain(["schema", "stock"], create_aapl_stock_table_view())
                    }
                )
            )

        assert isinstance(database.get_table("schema.stock"), SavedQuery)
        client.metrics.count.assert_not_called()

    def test_a_view_shadowed_by_another_view_is_not_counted(self):
        database = Database.create_for(team=self.team)
        database._add_views(
            TableNode(
                children={"aapl_stock_view": TableNode(name="aapl_stock_view", table=create_aapl_stock_table_view())}
            )
        )

        client = MagicMock()
        with patch("posthoganalytics.default_client", client):
            database._add_views(
                TableNode(
                    children={
                        "aapl_stock_view": TableNode(name="aapl_stock_view", table=create_nested_aapl_stock_view())
                    }
                )
            )

        client.metrics.count.assert_not_called()

    def _select(self, query: str, dialect: Literal["clickhouse", "hogql"] = "clickhouse") -> str:
        return prepare_and_print_ast(parse_select(query), self.context, dialect=dialect)[0]

    def test_view_table_select(self):
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
            hogql = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="hogql")
            self.assertEqual(
                hogql,
                "SELECT Date, Open, High, Low, Close, Volume, OpenInt FROM aapl_stock LIMIT 10",
            )

            clickhouse = self._select(query="SELECT * FROM aapl_stock_view LIMIT 10", dialect="clickhouse")

            self.assertEqual(
                clickhouse,
                "SELECT aapl_stock_view.Date AS Date, aapl_stock_view.Open AS Open, aapl_stock_view.High AS High, "
                "aapl_stock_view.Low AS Low, aapl_stock_view.Close AS Close, aapl_stock_view.Volume AS Volume, "
                "aapl_stock_view.OpenInt AS OpenInt FROM (SELECT aapl_stock.Date AS Date, aapl_stock.Open AS Open, "
                "aapl_stock.High AS High, aapl_stock.Low AS Low, aapl_stock.Close AS Close, aapl_stock.Volume AS Volume, "
                "aapl_stock.OpenInt AS OpenInt FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock) "
                "AS aapl_stock_view LIMIT 10",
            )

    def test_view_with_alias(self):
        with override_settings(
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=None,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=None,
        ):
            hogql = self._select(query="SELECT * FROM aapl_stock LIMIT 10", dialect="hogql")
            self.assertEqual(
                hogql,
                "SELECT Date, Open, High, Low, Close, Volume, OpenInt FROM aapl_stock LIMIT 10",
            )

            clickhouse = self._select(
                query="SELECT * FROM aapl_stock_view AS some_alias LIMIT 10",
                dialect="clickhouse",
            )

            self.assertEqual(
                clickhouse,
                "SELECT some_alias.Date AS Date, some_alias.Open AS Open, some_alias.High AS High, some_alias.Low AS Low, some_alias.Close AS Close, some_alias.Volume AS Volume, some_alias.OpenInt AS OpenInt FROM (SELECT aapl_stock.Date AS Date, aapl_stock.Open AS Open, aapl_stock.High AS High, aapl_stock.Low AS Low, aapl_stock.Close AS Close, aapl_stock.Volume AS Volume, aapl_stock.OpenInt AS OpenInt FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_1)s) AS aapl_stock) AS some_alias LIMIT 10",
            )

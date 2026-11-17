from typing import Literal, cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DataWarehouseEventsModifier,
    HogQLQueryModifiers,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import ExpressionField, FieldTraverser, SavedQuery, TableNode
from posthog.hogql.database.test.tables import (
    create_aapl_stock_s3_table,
    create_aapl_stock_table_self_referencing,
    create_aapl_stock_table_view,
    create_nested_aapl_stock_view,
)
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

from posthog.api.services.query import process_query_model

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

Origin = DataWarehouseSavedQuery.Origin


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


class TestModelsNamespaceDualRegistration(BaseTest):
    def _create(self, name: str, origin: str | None = None, query: str = "SELECT 1 AS id") -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            origin=origin,
            query={"kind": "HogQLQuery", "query": query},
            columns={"id": "String"},
        )

    @parameterized.expand(
        [
            ("null_origin", "revenue", None, "models.revenue", True),
            ("authored", "revenue", Origin.DATA_WAREHOUSE, "models.revenue", True),
            ("authored_dotted", "finance.revenue", Origin.DATA_WAREHOUSE, "models.finance.revenue", True),
            ("managed_viewset", "charge", Origin.MANAGED_VIEWSET, "models.charge", False),
            ("endpoint", "my_endpoint_v1", Origin.ENDPOINT, "models.my_endpoint_v1", False),
            ("already_in_namespace", "models.revenue", Origin.DATA_WAREHOUSE, "models.models.revenue", False),
        ]
    )
    def test_authored_model_resolves_under_the_models_root(
        self, _name: str, stored_name: str, origin: str | None, qualified_name: str, resolves: bool
    ) -> None:
        self._create(stored_name, origin)

        database = Database.create_for(team=self.team)

        assert database.has_table(qualified_name) is resolves
        if resolves:
            assert database.get_table(qualified_name) is database.get_table(stored_name)
        listed_name, unlisted_name = (qualified_name, stored_name) if resolves else (stored_name, qualified_name)
        assert database.get_view_names().count(listed_name) == 1
        assert unlisted_name not in database.get_view_names()
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database), include_fields=False)
        assert serialized[listed_name].name == listed_name
        assert unlisted_name not in serialized
        for requested in (stored_name, listed_name):
            partial = database.serialize(
                HogQLContext(team_id=self.team.pk, database=database), include_only={requested}
            )
            assert list(partial) == [listed_name]
        hydrated = cast(
            DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery(tables=[listed_name]))
        )
        assert list(hydrated.tables) == [listed_name]
        assert qualified_name not in database.get_all_table_names()
        assert qualified_name not in database.tables.resolve_visible_table_names()
        assert listed_name in database.get_visible_table_names()
        assert unlisted_name not in database.get_visible_table_names()

    def test_the_models_name_reaches_the_model_when_a_warehouse_table_holds_the_bare_name(self) -> None:
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        DataWarehouseTable.objects.create(
            name="revenue",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "table_only": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
            },
        )
        self._create("revenue")

        database = Database.create_for(team=self.team)

        assert isinstance(database.get_table("models.revenue"), SavedQuery)
        assert "revenue" in database.get_warehouse_table_names()
        assert database.get_view_names() == ["models.revenue"]
        assert {"revenue", "models.revenue"} <= set(database.get_visible_table_names())
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))
        assert list(serialized["models.revenue"].fields) == ["id"]

    def test_a_stored_models_name_wins_over_a_derived_one(self) -> None:
        legacy = self._create("arr", query="SELECT 'legacy' AS id")
        stored = self._create("models.arr", query="SELECT 'stored' AS id")

        database = Database.create_for(team=self.team)

        assert cast(SavedQuery, database.get_table("models.arr")).id == str(stored.id)
        assert cast(SavedQuery, database.get_table("arr")).id == str(legacy.id)
        assert sorted(database.get_view_names()) == ["arr", "models.arr"]

    def test_a_stored_model_nested_under_a_derived_name_does_not_hide_it(self) -> None:
        revenue = self._create("revenue")
        monthly = self._create("models.revenue.monthly")

        database = Database.create_for(team=self.team)

        assert database.has_table("models.revenue")
        assert cast(SavedQuery, database.get_table("models.revenue")).id == str(revenue.id)
        assert cast(SavedQuery, database.get_table("models.revenue.monthly")).id == str(monthly.id)

    @parameterized.expand(
        [
            ("stored_name", "revenue", False),
            ("models_name", "models.revenue", False),
            ("stored_models_name_wins", "models.revenue", True),
        ]
    )
    def test_event_modifier_maps_a_model_under_either_name(
        self, _name: str, modifier_table_name: str, stored_models_name_exists: bool
    ) -> None:
        self._create("revenue")
        if stored_models_name_exists:
            self._create("models.revenue")
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name=modifier_table_name,
                    id_field="real_id",
                    timestamp_field="event_time",
                    distinct_id_field="real_id",
                )
            ]
        )

        database = Database.create_for(team=self.team, modifiers=modifiers)

        for name in ["models.revenue"] if stored_models_name_exists else ["revenue", "models.revenue"]:
            fields = database.get_table(name).fields
            assert isinstance(fields["id"], ExpressionField)
            assert cast(ast.Field, fields["id"].expr).chain == ["real_id"]
            assert isinstance(fields["timestamp"], ExpressionField)
            assert cast(ast.Field, fields["timestamp"].expr).chain == ["event_time"]
        if stored_models_name_exists:
            assert not isinstance(database.get_table("revenue").fields["id"], ExpressionField)

    @parameterized.expand([("stored_name", "revenue"), ("models_name", "models.revenue")])
    def test_event_modifier_finds_the_events_join_under_either_name(self, _name: str, modifier_table_name: str) -> None:
        self._create("revenue")
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="revenue",
            source_table_key="id",
            joining_table_name="events",
            joining_table_key="distinct_id",
            field_name="events_join",
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name=modifier_table_name,
                    id_field="real_id",
                    timestamp_field="event_time",
                    distinct_id_field="real_id",
                )
            ]
        )

        database = Database.create_for(team=self.team, modifiers=modifiers)

        # The join holds the stored name, so a modifier that names the models form must still reach it.
        # Otherwise person_id silently falls back to the configured distinct_id_field.
        person_id = database.get_table(modifier_table_name).fields["person_id"]
        assert isinstance(person_id, FieldTraverser)
        assert person_id.chain == ["events_join", "person_id"]

    def test_a_legacy_model_named_models_keeps_its_slot(self) -> None:
        root = self._create("root_placeholder")
        DataWarehouseSavedQuery.objects.filter(pk=root.pk).update(name="models")
        revenue = self._create("revenue")

        database = Database.create_for(team=self.team)

        assert cast(SavedQuery, database.get_table("models")).id == str(root.id)
        assert cast(SavedQuery, database.get_table("models.revenue")).id == str(revenue.id)
        assert not database.has_table("models.models")

    def test_a_model_pruned_from_the_schema_is_unknown_under_both_names(self) -> None:
        self._create("revenue")
        self._create("costs")

        database = Database.create_for(team=self.team)
        database.prune_to_table_names({"costs"})

        assert database.has_table("models.costs")
        assert not database.has_table("models.revenue")
        with self.assertRaisesMessage(QueryError, "Unknown table `models.revenue`"):
            database.get_table("models.revenue")

    def test_the_models_name_is_not_a_table_of_its_own(self) -> None:
        self._create("revenue")

        database = Database.create_for(team=self.team)

        assert database.has_table("models.revenue")
        assert not [name for name in database.tables.resolve_all_table_names() if name.startswith("models.")]

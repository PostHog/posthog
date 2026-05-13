from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from products.catalog.backend.models import CatalogColumn, CatalogNode, CatalogRelationship


class TestCatalogHogQLExposure(BaseTest):
    def test_system_table_names_registered(self) -> None:
        names = set(SystemTables().children.keys())
        assert {"tables", "columns", "relationships"}.issubset(names)

    def test_system_tables_select_compiles_with_team_filter(self) -> None:
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        for name in ["tables", "columns", "relationships"]:
            sql, _ = prepare_and_print_ast(parse_select(f"SELECT * FROM system.{name}"), context, dialect="clickhouse")
            assert sql, f"system.{name} produced empty SQL"
            assert f"system__{name}" in sql, f"system.{name} should be aliased as system__{name}"
            if name in {"tables", "relationships"}:
                assert f"equals(system__{name}.team_id, {self.team.pk})" in sql

    def test_system_tables_describes_each_node(self) -> None:
        node = CatalogNode.objects.create(
            team=self.team,
            kind=CatalogNode.Kind.POSTHOG_TABLE,
            name="events",
            synthetic_description="Raw event stream",
        )
        CatalogColumn.objects.create(
            node=node,
            name="distinct_id",
            clickhouse_type="String",
            semantic_type=CatalogColumn.SemanticType.ENTITY_ID,
        )

        db = Database.create_for(team=self.team)
        tables_table = db.tables.children["system"].children["tables"].get()
        columns_table = db.tables.children["system"].children["columns"].get()
        assert isinstance(tables_table, Table)
        assert isinstance(columns_table, Table)

        assert "description" in tables_table.fields
        assert "synthetic_description" not in tables_table.fields
        assert "semantic_type" in columns_table.fields
        assert "pii_class" in columns_table.fields

    def test_relationships_table_exposes_kind_and_confidence(self) -> None:
        source = CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.WAREHOUSE_TABLE, name="orders")
        target = CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.WAREHOUSE_TABLE, name="customers")
        CatalogRelationship.objects.create(
            team=self.team,
            source_node=source,
            target_node=target,
            kind=CatalogRelationship.Kind.JOIN_CANDIDATE,
            confidence=0.75,
            reasoning="Shared 'customer_id' column",
        )

        db = Database.create_for(team=self.team)
        rel_table = db.tables.children["system"].children["relationships"].get()
        assert isinstance(rel_table, Table)
        assert "confidence" in rel_table.fields
        assert "reasoning" in rel_table.fields
        assert "kind" in rel_table.fields

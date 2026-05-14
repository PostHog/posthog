from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.database.schema.system_union import (
    deterministic_column_id,
    deterministic_relationship_id,
    deterministic_table_id,
)
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
            # The FROM-source is now a UNION of the Postgres-backed table and
            # synthesized rows from `system.py`. Both legs must appear.
            assert "postgresql(" in sql, f"system.{name} should still query Postgres via postgresql()"
            assert "UNION ALL" in sql, f"system.{name} should UNION ALL with synthesized rows"
            if name in {"tables", "relationships"}:
                assert f"equals(system__{name}.team_id, {self.team.pk})" in sql

    def test_system_tables_synthesizes_registry_entries(self) -> None:
        """Each entry in SystemTables surfaces in the `system.tables` UNION
        as a synthesized row with kind='system_table' and a deterministic id —
        no Postgres seeding required.
        """
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        sql, _ = prepare_and_print_ast(parse_select("SELECT * FROM system.tables"), context, dialect="clickhouse")

        names = [n for n, child in SystemTables().children.items() if isinstance(child.table, Table)]
        # `name` literals appear inside the synthesized SELECTs (escaped via single quotes).
        for name in names:
            assert f"\\'{name}\\'" in sql or f"'{name}'" in sql, f"synthesized name {name!r} missing from printed SQL"
        # Each entry gets a deterministic UUID so columns can join back to tables.
        sample_id = str(deterministic_table_id(names[0]))
        assert sample_id in sql, f"deterministic table id for {names[0]!r} missing from printed SQL"

    def test_system_columns_use_matching_node_ids(self) -> None:
        """Synthesized column rows use the same deterministic ids as the
        synthesized table rows, so `system.columns.node_id = system.tables.id`
        joins resolve.
        """
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        sql, _ = prepare_and_print_ast(parse_select("SELECT * FROM system.columns"), context, dialect="clickhouse")
        # Pick a known table+column pair from the registry.
        node_id = str(deterministic_table_id("activity_logs"))
        col_id = str(deterministic_column_id("activity_logs", "team_id"))
        assert node_id in sql, "synthesized node_id should reference the parent table's deterministic id"
        assert col_id in sql, "synthesized column_id should appear in the UNION"

    def test_system_columns_excludes_hidden_underscore_fields(self) -> None:
        """`_paused`, `_deleted`, and similar hidden raw fields back ExpressionField
        aliases — they're not what users SELECT. They should not appear in
        `system.columns`.
        """
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        sql, _ = prepare_and_print_ast(parse_select("SELECT * FROM system.columns"), context, dialect="clickhouse")
        # `_paused` is hidden on `batch_exports`. Its deterministic id should not appear.
        hidden_col_id = str(deterministic_column_id("batch_exports", "_paused"))
        assert hidden_col_id not in sql, "hidden `_paused` column must not be synthesized"
        # The visible non-underscore columns from the same table should still appear.
        visible_col_id = str(deterministic_column_id("batch_exports", "name"))
        assert visible_col_id in sql, "visible `name` column must still be synthesized"

    def test_system_relationships_includes_declared_edges(self) -> None:
        """`alerts.insight_id → insights.id` was declared inline in system.py;
        it must show up in the synthesized `system.relationships` rows.
        """
        db = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)
        sql, _ = prepare_and_print_ast(
            parse_select("SELECT * FROM system.relationships"), context, dialect="clickhouse"
        )
        rel_id = str(deterministic_relationship_id("alerts", "insight_id", "insights", "id", "foreign_key"))
        assert rel_id in sql, "alerts.insight_id → insights.id edge missing from printed SQL"
        # Universal team_id → teams.id edge for at least one table.
        team_rel_id = str(deterministic_relationship_id("alerts", "team_id", "teams", "id", "foreign_key"))
        assert team_rel_id in sql, "alerts.team_id → teams.id edge missing from printed SQL"

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

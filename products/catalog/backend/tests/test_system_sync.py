from posthog.test.base import BaseTest

from posthog.hogql.database.schema.system import SystemTables

from products.catalog.backend.logic import sync_system_tables_for_team
from products.catalog.backend.models import CatalogColumn, CatalogNode
from products.catalog.backend.system_registry import iter_system_tables


class TestSyncSystemTablesForTeam(BaseTest):
    def test_creates_one_node_per_system_table(self) -> None:
        expected = sum(1 for _ in iter_system_tables())

        count = sync_system_tables_for_team(self.team.pk)

        assert count == expected
        node_count = CatalogNode.objects.filter(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE).count()
        assert node_count == expected

    def test_creates_columns_for_tasks_table(self) -> None:
        sync_system_tables_for_team(self.team.pk)

        node = CatalogNode.objects.get(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE, name="tasks")
        column_names = set(node.columns.values_list("name", flat=True))

        assert "id" in column_names
        assert "title" in column_names
        assert "description" in column_names
        # ExpressionField aliases are visible; their raw _* counterparts are hidden.
        assert "internal" in column_names
        assert "deleted" in column_names
        assert "_internal" not in column_names
        assert "_deleted" not in column_names

    def test_skips_hidden_fields(self) -> None:
        sync_system_tables_for_team(self.team.pk)

        node = CatalogNode.objects.get(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE, name="batch_exports")
        column_names = set(node.columns.values_list("name", flat=True))

        assert "paused" in column_names
        assert "_paused" not in column_names
        assert "deleted" in column_names
        assert "_deleted" not in column_names

    def test_is_idempotent(self) -> None:
        first = sync_system_tables_for_team(self.team.pk)
        first_node_ids = set(
            CatalogNode.objects.filter(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE).values_list("id", flat=True)
        )
        first_column_count = CatalogColumn.objects.filter(team=self.team, node__kind="system_table").count()

        second = sync_system_tables_for_team(self.team.pk)
        second_node_ids = set(
            CatalogNode.objects.filter(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE).values_list("id", flat=True)
        )
        second_column_count = CatalogColumn.objects.filter(team=self.team, node__kind="system_table").count()

        assert first == second
        assert first_node_ids == second_node_ids
        assert first_column_count == second_column_count

    def test_only_writes_for_target_team(self) -> None:
        other = self._create_other_team()

        sync_system_tables_for_team(self.team.pk)

        assert CatalogNode.objects.filter(team=self.team, kind=CatalogNode.Kind.SYSTEM_TABLE).exists()
        assert not CatalogNode.objects.filter(team=other, kind=CatalogNode.Kind.SYSTEM_TABLE).exists()

    def test_column_clickhouse_type_normalized(self) -> None:
        sync_system_tables_for_team(self.team.pk)

        # `tasks.id` is a StringDatabaseField → "String"
        column = CatalogColumn.objects.get(
            team=self.team,
            node__kind=CatalogNode.Kind.SYSTEM_TABLE,
            node__name="tasks",
            name="id",
        )
        assert column.clickhouse_type == "String"

        # `tasks.created_at` is DateTimeDatabaseField → "DateTime"
        created_at = CatalogColumn.objects.get(
            team=self.team,
            node__kind=CatalogNode.Kind.SYSTEM_TABLE,
            node__name="tasks",
            name="created_at",
        )
        assert created_at.clickhouse_type == "DateTime"

    def _create_other_team(self):
        from posthog.models.team import Team

        return Team.objects.create(organization=self.organization, name="Other")


class TestSystemRegistry(BaseTest):
    def test_iter_system_tables_matches_systemtables_children(self) -> None:
        names_from_iter = {name for name, _ in iter_system_tables()}
        names_from_children = {
            name for name, child in SystemTables().children.items() if hasattr(child.table, "fields")
        }
        assert names_from_iter == names_from_children

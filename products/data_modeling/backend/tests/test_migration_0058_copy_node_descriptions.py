from typing import Any
from uuid import uuid4

from posthog.test.base import NonAtomicTestMigrations


class TestCopyNodeDescriptionsToAnnotations(NonAtomicTestMigrations):
    app = "data_modeling"
    migrate_from = "0057_datamodelingjob_drop_bytes_read_column"
    migrate_to = "0058_copy_node_descriptions_to_annotations"

    def setUpBeforeMigration(self, apps: Any) -> None:
        DAG = apps.get_model("data_modeling", "DAG")
        Node = apps.get_model("data_modeling", "Node")
        SavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        Annotation = apps.get_model("data_modeling", "DataWarehouseSavedQueryColumnAnnotation")
        Table = apps.get_model("warehouse_sources", "DataWarehouseTable")
        dag = DAG.objects.create(team_id=self.team.id, name=f"posthog_{self.team.id}")

        def view(name: str, node_text: str, *, deleted: bool = False) -> Any:
            saved_query = SavedQuery.objects.create(
                team_id=self.team.id, name=name, query={"query": "SELECT 1", "kind": "HogQLQuery"}, deleted=deleted
            )
            Node.objects.create(
                id=uuid4(), team_id=self.team.id, dag=dag, name=name, saved_query=saved_query, description=node_text
            )
            return saved_query

        def annotate(saved_query: Any, text: str, source: str, *, user_edited: bool) -> None:
            Annotation.objects.create(
                team_id=self.team.id,
                saved_query=saved_query,
                column_name="",
                description=text,
                description_source=source,
                is_user_edited=user_edited,
            )

        self.no_annotation = view("no_annotation", "Node text").id
        ai_view = view("ai_annotation", "Node text")
        annotate(ai_view, "AI text", "ai_generated", user_edited=False)
        self.ai_annotation = ai_view.id
        user_view = view("user_annotation", "Node text")
        annotate(user_view, "User text", "user_edited", user_edited=True)
        self.user_annotation = user_view.id
        self.deleted_view = view("deleted_view", "Node text", deleted=True).id
        self.blank_node = view("blank_node", "").id

        table = Table.objects.create(
            team_id=self.team.id, name="orders", format="Parquet", url_pattern="https://bucket.s3/data/*"
        )
        Node.objects.create(
            id=uuid4(),
            team_id=self.team.id,
            dag=dag,
            name="orders",
            type="table",
            properties={"warehouse_table_id": str(table.id)},
            description="Table text",
        )
        self.table = table.id
        Node.objects.create(
            id=uuid4(),
            team_id=self.team.id,
            dag=dag,
            name="malformed_table",
            type="table",
            properties={"warehouse_table_id": 123},
            description="Malformed node text",
        )

    def _view_row(self, saved_query_id: Any) -> Any:
        Annotation = self.apps.get_model("data_modeling", "DataWarehouseSavedQueryColumnAnnotation")  # type: ignore[union-attr]
        return Annotation.objects.filter(saved_query_id=saved_query_id, column_name="").first()

    def test_copy_rules(self) -> None:
        created = self._view_row(self.no_annotation)
        assert (created.description, created.description_source, created.is_user_edited) == (
            "Node text",
            "user_edited",
            True,
        )
        replaced = self._view_row(self.ai_annotation)
        assert (replaced.description, replaced.description_source, replaced.is_user_edited, replaced.ai_model) == (
            "Node text",
            "user_edited",
            True,
            None,
        )
        assert self._view_row(self.user_annotation).description == "User text"
        assert self._view_row(self.deleted_view) is None
        assert self._view_row(self.blank_node) is None

        TableAnnotation = self.apps.get_model("warehouse_sources", "WarehouseColumnAnnotation")  # type: ignore[union-attr]
        table_row = TableAnnotation.objects.get(table_id=self.table, column_name="")
        assert (table_row.description, table_row.is_user_edited) == ("Table text", True)

from posthog.test.base import BaseTest

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from parameterized import parameterized

from products.catalog.backend.models import CatalogColumn, CatalogNode, CatalogRelationship, CatalogTraversalRun
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable


class TestCatalogNode(BaseTest):
    @parameterized.expand(
        [
            (CatalogNode.Kind.WAREHOUSE_TABLE, "stripe_customers"),
            (CatalogNode.Kind.SAVED_QUERY, "user_revenue_view"),
            (CatalogNode.Kind.SYSTEM_TABLE, "dashboards"),
            (CatalogNode.Kind.POSTHOG_TABLE, "events"),
        ]
    )
    def test_create_node_per_kind(self, kind: str, name: str) -> None:
        node = CatalogNode.objects.create(team=self.team, kind=kind, name=name)
        assert node.id is not None
        assert node.kind == kind
        assert node.first_seen_at is not None
        assert node.last_seen_at is not None
        assert node.synthetic_description is None
        assert node.tags == []

    def test_unique_constraint_on_kind_name(self) -> None:
        CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.POSTHOG_TABLE, name="events")
        with self.assertRaises(IntegrityError):
            CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.POSTHOG_TABLE, name="events")

    def test_same_name_different_kind_is_allowed(self) -> None:
        CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.POSTHOG_TABLE, name="events")
        CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.SAVED_QUERY, name="events")
        assert CatalogNode.objects.filter(team=self.team, name="events").count() == 2

    def test_generic_foreign_key_resolves_to_warehouse_table(self) -> None:
        warehouse_table = DataWarehouseTable.objects.create(team=self.team, name="stripe_customers", format="Parquet")
        node = CatalogNode.objects.create(
            team=self.team,
            kind=CatalogNode.Kind.WAREHOUSE_TABLE,
            name="stripe_customers",
            content_type=ContentType.objects.get_for_model(DataWarehouseTable),
            object_id=warehouse_table.id,
        )
        assert node.target == warehouse_table

    def test_signal_deletes_node_when_warehouse_table_deleted(self) -> None:
        warehouse_table = DataWarehouseTable.objects.create(team=self.team, name="stripe_customers", format="Parquet")
        node = CatalogNode.objects.create(
            team=self.team,
            kind=CatalogNode.Kind.WAREHOUSE_TABLE,
            name="stripe_customers",
            content_type=ContentType.objects.get_for_model(DataWarehouseTable),
            object_id=warehouse_table.id,
        )
        warehouse_table.delete()
        assert not CatalogNode.objects.filter(pk=node.pk).exists()

    def test_signal_deletes_node_when_saved_query_deleted(self) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        node = CatalogNode.objects.create(
            team=self.team,
            kind=CatalogNode.Kind.SAVED_QUERY,
            name="my_view",
            content_type=ContentType.objects.get_for_model(DataWarehouseSavedQuery),
            object_id=saved_query.id,
        )
        saved_query.delete()
        assert not CatalogNode.objects.filter(pk=node.pk).exists()


class TestCatalogColumn(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.node = CatalogNode.objects.create(team=self.team, kind=CatalogNode.Kind.POSTHOG_TABLE, name="events")

    def test_create_column(self) -> None:
        column = CatalogColumn.objects.create(
            node=self.node, name="distinct_id", clickhouse_type="String", hogql_type="StringDatabaseField"
        )
        assert column.name == "distinct_id"
        assert column.nullable is True
        assert column.semantic_type is None

    def test_unique_constraint_per_node(self) -> None:
        CatalogColumn.objects.create(node=self.node, name="distinct_id")
        with self.assertRaises(IntegrityError):
            CatalogColumn.objects.create(node=self.node, name="distinct_id")

    def test_cascade_from_node(self) -> None:
        column = CatalogColumn.objects.create(node=self.node, name="distinct_id")
        self.node.delete()
        assert not CatalogColumn.objects.filter(pk=column.pk).exists()


class TestCatalogRelationship(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source_node = CatalogNode.objects.create(
            team=self.team, kind=CatalogNode.Kind.WAREHOUSE_TABLE, name="orders"
        )
        self.target_node = CatalogNode.objects.create(
            team=self.team, kind=CatalogNode.Kind.WAREHOUSE_TABLE, name="customers"
        )

    def test_create_relationship_with_required_fields(self) -> None:
        rel = CatalogRelationship.objects.create(
            team=self.team,
            source_node=self.source_node,
            target_node=self.target_node,
            kind=CatalogRelationship.Kind.JOIN_CANDIDATE,
            confidence=0.85,
            reasoning="Column 'customer_id' on orders looks like an FK to customers.id",
        )
        assert rel.status == CatalogRelationship.Status.PROPOSED
        assert rel.confidence == 0.85
        assert rel.reasoning.startswith("Column 'customer_id'")

    def test_unique_edge_constraint(self) -> None:
        # Postgres treats NULLs as distinct in unique constraints by default, so the
        # column FKs must be populated for this assertion to bite. The cron writer
        # de-dupes column-less edges application-side via update_or_create.
        source_column = CatalogColumn.objects.create(node=self.source_node, name="customer_id")
        target_column = CatalogColumn.objects.create(node=self.target_node, name="id")
        CatalogRelationship.objects.create(
            team=self.team,
            source_node=self.source_node,
            source_column=source_column,
            target_node=self.target_node,
            target_column=target_column,
            kind=CatalogRelationship.Kind.FOREIGN_KEY,
            confidence=0.9,
        )
        with self.assertRaises(IntegrityError):
            CatalogRelationship.objects.create(
                team=self.team,
                source_node=self.source_node,
                source_column=source_column,
                target_node=self.target_node,
                target_column=target_column,
                kind=CatalogRelationship.Kind.FOREIGN_KEY,
                confidence=0.7,
            )

    def test_different_kind_between_same_nodes_is_allowed(self) -> None:
        CatalogRelationship.objects.create(
            team=self.team,
            source_node=self.source_node,
            target_node=self.target_node,
            kind=CatalogRelationship.Kind.FOREIGN_KEY,
            confidence=0.9,
        )
        CatalogRelationship.objects.create(
            team=self.team,
            source_node=self.source_node,
            target_node=self.target_node,
            kind=CatalogRelationship.Kind.LINEAGE,
            confidence=1.0,
        )
        assert (
            CatalogRelationship.objects.filter(source_node=self.source_node, target_node=self.target_node).count() == 2
        )


class TestCatalogTraversalRun(BaseTest):
    def test_create_run(self) -> None:
        run = CatalogTraversalRun.objects.create(
            team=self.team,
            trigger=CatalogTraversalRun.Trigger.CRON,
        )
        assert run.status == CatalogTraversalRun.Status.QUEUED
        assert run.nodes_processed == 0
        assert run.config == {}

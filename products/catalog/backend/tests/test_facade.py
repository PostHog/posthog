from posthog.test.base import BaseTest

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import (
    CatalogGraphDTO,
    CatalogNodeDTO,
    ProposeRelationshipParams,
    UpdateColumnParams,
    UpdateNodeParams,
    UpdateRelationshipParams,
    UpsertColumnParams,
    UpsertNodeParams,
)


class TestCatalogAPIUpsert(BaseTest):
    def test_upsert_node_creates_new(self) -> None:
        dto = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="posthog_table",
                name="events",
                synthetic_description="Raw event stream",
            )
        )
        assert isinstance(dto, CatalogNodeDTO)
        assert dto.name == "events"
        assert dto.description == "Raw event stream"
        assert dto.last_traversed_at is not None

    def test_upsert_node_is_idempotent(self) -> None:
        first = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))
        second = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="posthog_table",
                name="events",
                synthetic_description="Raw event stream",
            )
        )
        assert first.id == second.id
        assert second.description == "Raw event stream"

    def test_upsert_column_is_idempotent(self) -> None:
        node = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))
        first = CatalogAPI.upsert_column(
            UpsertColumnParams(node_id=node.id, name="distinct_id", clickhouse_type="String")
        )
        second = CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=node.id,
                name="distinct_id",
                clickhouse_type="String",
                synthetic_description="Identifier for the user that emitted this event",
                semantic_type="entity_id",
            )
        )
        assert first.id == second.id
        assert second.description is not None and second.description.startswith("Identifier")
        assert second.semantic_type == "entity_id"

    def test_propose_relationship_is_idempotent_on_edge_tuple(self) -> None:
        source = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="orders"))
        target = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="customers")
        )
        first = CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=source.id,
                target_node_id=target.id,
                kind="foreign_key",
                confidence=0.7,
                reasoning="First pass",
            )
        )
        second = CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=source.id,
                target_node_id=target.id,
                kind="foreign_key",
                confidence=0.9,
                reasoning="Second pass — stronger evidence",
            )
        )
        assert first.id == second.id
        assert second.confidence == 0.9
        assert second.reasoning.startswith("Second pass")


class TestCatalogAPIGetGraph(BaseTest):
    def test_get_graph_returns_nodes_columns_and_relationships(self) -> None:
        events = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))
        persons = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="persons"))
        CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=events.id, name="distinct_id", clickhouse_type="String", semantic_type="entity_id"
            )
        )
        CatalogAPI.upsert_column(
            UpsertColumnParams(node_id=persons.id, name="id", clickhouse_type="UUID", semantic_type="entity_id")
        )
        CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=events.id,
                target_node_id=persons.id,
                kind="foreign_key",
                confidence=0.8,
                reasoning="events.distinct_id resolves to a person",
            )
        )

        graph = CatalogAPI.get_graph(self.team.pk)
        assert isinstance(graph, CatalogGraphDTO)
        assert len(graph.nodes) == 2
        assert {n.name for n in graph.nodes} == {"events", "persons"}
        assert len(graph.relationships) == 1
        assert graph.relationships[0].confidence == 0.8

    def test_list_nodes_returns_team_nodes_ordered(self) -> None:
        CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="orders", business_domain="billing")
        )
        CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events", business_domain="product_usage")
        )
        CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="invoices", business_domain="billing")
        )

        nodes = CatalogAPI.list_nodes(self.team.pk)

        names = [n.name for n in nodes]
        assert names == ["invoices", "orders", "events"]

    def test_get_graph_does_not_leak_across_teams(self) -> None:
        CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="posthog_table", name="events"))

        from posthog.models import Organization, Team
        from posthog.models.project import Project

        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        graph = CatalogAPI.get_graph(other_team.pk)
        assert graph.nodes == ()
        assert graph.relationships == ()


class TestCatalogAPIUpdate(BaseTest):
    def test_update_node_writes_only_supplied_fields(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="warehouse_table",
                name="stripe_charges",
                synthetic_description="initial",
                semantic_role="fact",
                business_domain="billing",
                tags=("stripe",),
            )
        )

        updated = CatalogAPI.update_node(
            UpdateNodeParams(
                team_id=self.team.pk,
                node_id=node.id,
                synthetic_description="refined description",
            )
        )

        assert updated is not None
        assert updated.description == "refined description"
        assert updated.semantic_role == "fact"
        assert updated.business_domain == "billing"
        assert updated.tags == ("stripe",)

    def test_update_node_status_records_review(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_charges")
        )
        assert node.status == "proposed"
        assert node.reviewed_at is None

        approved = CatalogAPI.update_node(
            UpdateNodeParams(
                team_id=self.team.pk,
                node_id=node.id,
                status="approved",
                reviewed_by_id=self.user.pk,
            )
        )

        assert approved is not None
        assert approved.status == "approved"
        assert approved.reviewed_at is not None

    def test_update_node_returns_none_for_missing(self) -> None:
        import uuid

        result = CatalogAPI.update_node(
            UpdateNodeParams(team_id=self.team.pk, node_id=uuid.uuid4(), synthetic_description="x")
        )
        assert result is None

    def test_update_node_does_not_leak_across_teams(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_charges")
        )
        result = CatalogAPI.update_node(
            UpdateNodeParams(team_id=self.team.pk + 9999, node_id=node.id, synthetic_description="hijack")
        )
        assert result is None

    def test_update_column_writes_only_supplied_fields(self) -> None:
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_charges")
        )
        column = CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=node.id,
                name="amount_usd_cents",
                clickhouse_type="UInt64",
                semantic_type="measure",
                pii_class="public",
            )
        )

        updated = CatalogAPI.update_column(
            UpdateColumnParams(
                team_id=self.team.pk,
                column_id=column.id,
                synthetic_description="Charge amount in USD cents",
                semantic_type="monetary",
            )
        )

        assert updated is not None
        assert updated.description == "Charge amount in USD cents"
        assert updated.semantic_type == "monetary"
        assert updated.pii_class == "public"

    def test_update_relationship_accept_records_review(self) -> None:
        source = CatalogAPI.upsert_node(UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="orders"))
        target = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="customers")
        )
        rel = CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=source.id,
                target_node_id=target.id,
                kind="foreign_key",
                confidence=0.6,
            )
        )
        assert rel.status == "proposed"

        accepted = CatalogAPI.update_relationship(
            UpdateRelationshipParams(
                team_id=self.team.pk,
                relationship_id=rel.id,
                status="accepted",
                reviewed_by_id=self.user.pk,
            )
        )

        assert accepted is not None
        assert accepted.status == "accepted"


class TestCatalogAPIDerivation(BaseTest):
    """Rule-based proposer over the catalog state."""

    def _setup_minimal_catalog(self) -> None:
        # One warehouse table with a monetary column and a dimension column.
        node = CatalogAPI.upsert_node(
            UpsertNodeParams(
                team_id=self.team.pk,
                kind="warehouse_table",
                name="stripe_charges",
                business_domain="billing",
            )
        )
        CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=node.id,
                name="amount_usd_cents",
                clickhouse_type="UInt64",
                semantic_type="monetary",
            )
        )
        CatalogAPI.upsert_column(
            UpsertColumnParams(
                node_id=node.id,
                name="country",
                clickhouse_type="String",
                semantic_type="dimension",
            )
        )

    def test_derive_creates_an_entity_per_node_by_default(self) -> None:
        self._setup_minimal_catalog()
        result = CatalogAPI.derive_catalog(self.team.pk)
        assert result.entities_created == 1
        assert result.metrics_created == 1
        assert result.dimensions_created == 1

    def test_derive_is_idempotent(self) -> None:
        self._setup_minimal_catalog()
        first = CatalogAPI.derive_catalog(self.team.pk)
        second = CatalogAPI.derive_catalog(self.team.pk)
        assert first.entities_created == 1
        # Second run finds the same rows; nothing new is created.
        assert second.entities_created == 0
        assert second.metrics_created == 0
        assert second.dimensions_created == 0

    def test_derive_clusters_same_entity_relationships(self) -> None:
        stripe = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="stripe_customers")
        )
        users = CatalogAPI.upsert_node(
            UpsertNodeParams(team_id=self.team.pk, kind="warehouse_table", name="auth_users")
        )
        CatalogAPI.propose_relationship(
            ProposeRelationshipParams(
                team_id=self.team.pk,
                source_node_id=stripe.id,
                target_node_id=users.id,
                kind="same_entity",
                confidence=1.0,
            )
        )

        result = CatalogAPI.derive_catalog(self.team.pk)
        # Both nodes collapse into one entity.
        assert result.entities_created == 1

        entities = CatalogAPI.list_entities(self.team.pk)
        assert len(entities) == 1
        assert len(entities[0].member_node_ids) == 2

    def test_browser_bundle_returns_full_state(self) -> None:
        self._setup_minimal_catalog()
        CatalogAPI.derive_catalog(self.team.pk)
        browser = CatalogAPI.get_browser(self.team.pk)
        assert len(browser.entities) == 1
        assert len(browser.metrics) == 1
        assert len(browser.dimensions) == 1

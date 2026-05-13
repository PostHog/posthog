from posthog.test.base import BaseTest

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import (
    CatalogGraphDTO,
    CatalogNodeDTO,
    ProposeRelationshipParams,
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
        assert second.description.startswith("Identifier")
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

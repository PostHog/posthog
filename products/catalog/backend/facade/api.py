from uuid import UUID

from products.catalog.backend import logic
from products.catalog.backend.facade.contracts import (
    CatalogColumnDTO,
    CatalogGraphDTO,
    CatalogMetricDTO,
    CatalogNodeDTO,
    CatalogRelationshipDTO,
    CatalogTraversalRunDTO,
    ProposeRelationshipParams,
    UpdateColumnParams,
    UpdateMetricParams,
    UpdateNodeParams,
    UpdateRelationshipParams,
    UpsertColumnParams,
    UpsertMetricParams,
    UpsertNodeParams,
)


class CatalogAPI:
    """The only thing other products may import from products.catalog."""

    @staticmethod
    def get_graph(team_id: int) -> CatalogGraphDTO:
        return logic.get_graph(team_id)

    @staticmethod
    def get_node(team_id: int, node_id: UUID) -> CatalogNodeDTO | None:
        return logic.get_node(team_id, node_id)

    @staticmethod
    def list_nodes(team_id: int) -> list[CatalogNodeDTO]:
        return logic.list_nodes(team_id)

    @staticmethod
    def get_column(team_id: int, column_id: UUID) -> CatalogColumnDTO | None:
        return logic.get_column(team_id, column_id)

    @staticmethod
    def get_relationship(team_id: int, relationship_id: UUID) -> CatalogRelationshipDTO | None:
        return logic.get_relationship(team_id, relationship_id)

    @staticmethod
    def upsert_node(params: UpsertNodeParams) -> CatalogNodeDTO:
        return logic.upsert_node(params)

    @staticmethod
    def upsert_column(params: UpsertColumnParams) -> CatalogColumnDTO:
        return logic.upsert_column(params)

    @staticmethod
    def upsert_metric(params: UpsertMetricParams) -> CatalogMetricDTO:
        """Upsert a semantic metric and its bound CatalogNode(kind=metric).

        Idempotent on (team, name). See `logic.upsert_metric` for the atomic
        write semantics — metric row and node row are created/updated together.
        """
        return logic.upsert_metric(params)

    @staticmethod
    def list_metrics(team_id: int) -> list[CatalogMetricDTO]:
        return logic.list_metrics(team_id)

    @staticmethod
    def get_metric(team_id: int, metric_id: UUID) -> CatalogMetricDTO | None:
        return logic.get_metric(team_id, metric_id)

    @staticmethod
    def update_metric(params: UpdateMetricParams) -> CatalogMetricDTO | None:
        return logic.update_metric(params)

    @staticmethod
    def propose_relationship(params: ProposeRelationshipParams) -> CatalogRelationshipDTO:
        """Insert/update a catalog relationship.

        `confidence == 1.0` writes status=ACCEPTED on insert; any other value
        writes status=PROPOSED. Status is never changed on update — human
        review actions stick across re-runs. See `logic.propose_relationship`.
        """
        return logic.propose_relationship(params)

    @staticmethod
    def update_node(params: UpdateNodeParams) -> CatalogNodeDTO | None:
        return logic.update_node(params)

    @staticmethod
    def update_column(params: UpdateColumnParams) -> CatalogColumnDTO | None:
        return logic.update_column(params)

    @staticmethod
    def update_relationship(params: UpdateRelationshipParams) -> CatalogRelationshipDTO | None:
        return logic.update_relationship(params)

    @staticmethod
    def list_traversal_runs(team_id: int) -> list[CatalogTraversalRunDTO]:
        """Recent CatalogTraversalRun rows for the team, newest first."""
        return logic.list_traversal_runs(team_id)

    @staticmethod
    async def start_traversal(team_id: int) -> str:
        """Fire-and-forget kickoff of CatalogTraversalWorkflow. Returns workflow id.

        Imported inline to avoid a facade <-> temporal cycle: `propose.py`
        imports `CatalogAPI`, and the temporal package eagerly loads its
        activities, so importing the client at module scope deadlocks the
        partial module on first load.
        """
        from products.catalog.backend.temporal.client import start_catalog_traversal_workflow_async

        return await start_catalog_traversal_workflow_async(team_id, trigger="api")

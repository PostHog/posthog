from uuid import UUID

from products.catalog.backend import logic
from products.catalog.backend.facade.contracts import (
    CatalogColumnDTO,
    CatalogGraphDTO,
    CatalogNodeDTO,
    CatalogRelationshipDTO,
    ProposeRelationshipParams,
    UpdateColumnParams,
    UpdateNodeParams,
    UpdateRelationshipParams,
    UpsertColumnParams,
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

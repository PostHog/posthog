from uuid import UUID

from products.catalog.backend import logic
from products.catalog.backend.facade.contracts import (
    CatalogColumnDTO,
    CatalogGraphDTO,
    CatalogNodeDTO,
    CatalogRelationshipDTO,
    ProposeRelationshipParams,
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
    def upsert_node(params: UpsertNodeParams) -> CatalogNodeDTO:
        return logic.upsert_node(params)

    @staticmethod
    def upsert_column(params: UpsertColumnParams) -> CatalogColumnDTO:
        return logic.upsert_column(params)

    @staticmethod
    def propose_relationship(params: ProposeRelationshipParams) -> CatalogRelationshipDTO:
        return logic.propose_relationship(params)

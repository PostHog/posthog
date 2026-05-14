from uuid import UUID

from posthog.models.team.team import Team

from products.catalog.backend import logic
from products.catalog.backend.facade.contracts import (
    AppendColumnNoteParams,
    AppendNodeNoteParams,
    CatalogColumnDTO,
    CatalogGraphDTO,
    CatalogMetricDTO,
    CatalogNodeContextDTO,
    CatalogNodeDTO,
    CatalogRelationshipDTO,
    ProposeRelationshipParams,
    RecordJoinParams,
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

    # -- Conversation-driven appends -----------------------------------------
    #
    # These power the PostHog AI `update_catalog` tool. They resolve the HogQL
    # kind for `table_name`, upsert any missing node / column rows, and append
    # the caller-supplied `[attribution] note` line to the existing description
    # (or to relationship.reasoning, for joins). `team` is passed explicitly so
    # HogQL kind resolution doesn't require a second Team fetch in the logic
    # layer.

    @staticmethod
    def get_node_context(team: Team, table_name: str) -> CatalogNodeContextDTO | None:
        """Return the catalog's view of `table_name` for read-side injection.

        Returns None when HogQL doesn't recognize the table or when there's no
        CatalogNode for it yet (traversal hasn't run, or the table is brand new).
        Callers should treat the absence of a context as "no catalog signal" and
        fall back to whatever they were already rendering.
        """
        return logic.get_node_context(team, table_name)

    @staticmethod
    def append_node_note(team: Team, params: AppendNodeNoteParams) -> CatalogNodeDTO:
        return logic.append_node_note(team, params)

    @staticmethod
    def append_column_note(team: Team, params: AppendColumnNoteParams) -> CatalogColumnDTO:
        return logic.append_column_note(team, params)

    @staticmethod
    def record_join(team: Team, params: RecordJoinParams) -> CatalogRelationshipDTO:
        return logic.record_join(team, params)

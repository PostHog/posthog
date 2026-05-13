"""
DRF views for catalog.

Three write endpoints the agent uses to populate the semantic graph:
  - POST /catalog/nodes/         upsert a table/saved-query/system-table node
  - POST /catalog/columns/       upsert a column under an existing node
  - POST /catalog/relationships/ propose a relationship between two nodes

Reads happen via HogQL system tables (`system.tables`, `system.columns`,
`system.relationships`) rather than REST — agents in MCP v2 SELECT what they need.
This file stays small on purpose: validate → call facade → serialize.
"""

from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api as catalog_api
from ..facade.contracts import ProposeRelationshipParams, UpsertColumnParams, UpsertNodeParams
from .serializers import (
    CatalogColumnDTOSerializer,
    CatalogNodeDTOSerializer,
    CatalogRelationshipDTOSerializer,
    ProposeRelationshipInputSerializer,
    UpsertColumnInputSerializer,
    UpsertNodeInputSerializer,
)

CATALOG_TAG = "catalog"


@extend_schema(tags=[CATALOG_TAG])
class CatalogNodeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Catalog nodes — the "table-shaped things" the agent reasons over.

    Idempotent upsert keyed by (team, kind, name): re-posting with the same
    name updates the row in place, so agent traversal runs can re-author
    descriptions safely without piling up duplicates.
    """

    scope_object = "catalog"
    scope_object_write_actions = ["create"]
    scope_object_read_actions: list[str] = []

    @validated_request(
        request_serializer=UpsertNodeInputSerializer,
        responses={201: OpenApiResponse(response=CatalogNodeDTOSerializer)},
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Upsert a catalog node and its agent-authored descriptions."""
        data = request.validated_data
        params = UpsertNodeParams(
            team_id=cast(int, self.team_id),
            kind=data["kind"],
            name=data["name"],
            warehouse_table_id=data.get("warehouse_table_id"),
            saved_query_id=data.get("saved_query_id"),
            synthetic_description=data.get("synthetic_description"),
            semantic_role=data.get("semantic_role"),
            business_domain=data.get("business_domain"),
            tags=tuple(data.get("tags") or ()),
            generator_model=data.get("generator_model"),
            confidence=data.get("confidence"),
        )
        node = catalog_api.CatalogAPI.upsert_node(params)
        return Response(CatalogNodeDTOSerializer(instance=node).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=[CATALOG_TAG])
class CatalogColumnViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Columns under a CatalogNode. Idempotent upsert keyed by (node, name).

    Team isolation is enforced by the parent node — the column's team_id is
    derived from the node's team_id in the facade, not trusted from the request.
    """

    scope_object = "catalog"
    scope_object_write_actions = ["create"]
    scope_object_read_actions: list[str] = []

    @validated_request(
        request_serializer=UpsertColumnInputSerializer,
        responses={201: OpenApiResponse(response=CatalogColumnDTOSerializer)},
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Upsert a column on a catalog node with its typing and description."""
        data = request.validated_data
        params = UpsertColumnParams(
            node_id=data["node_id"],
            name=data["name"],
            position=data.get("position", 0),
            clickhouse_type=data.get("clickhouse_type"),
            hogql_type=data.get("hogql_type"),
            nullable=data.get("nullable", True),
            synthetic_description=data.get("synthetic_description"),
            semantic_type=data.get("semantic_type"),
            pii_class=data.get("pii_class"),
            generator_model=data.get("generator_model"),
            confidence=data.get("confidence"),
        )
        column = catalog_api.CatalogAPI.upsert_column(params)
        return Response(CatalogColumnDTOSerializer(instance=column).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=[CATALOG_TAG])
class CatalogRelationshipViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Edges between catalog nodes.

    Proposals always start in `proposed` status. Confirmed relationships are
    promoted via the review workflow (out of scope for this endpoint).
    Re-proposing the same (source, target, columns, kind) updates confidence
    and reasoning rather than creating a duplicate edge.
    """

    scope_object = "catalog"
    scope_object_write_actions = ["create"]
    scope_object_read_actions: list[str] = []

    @validated_request(
        request_serializer=ProposeRelationshipInputSerializer,
        responses={201: OpenApiResponse(response=CatalogRelationshipDTOSerializer)},
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Propose a relationship between two catalog nodes."""
        data = request.validated_data
        params = ProposeRelationshipParams(
            team_id=cast(int, self.team_id),
            source_node_id=data["source_node_id"],
            target_node_id=data["target_node_id"],
            kind=data["kind"],
            confidence=data["confidence"],
            source_column_id=data.get("source_column_id"),
            target_column_id=data.get("target_column_id"),
            reasoning=data.get("reasoning", ""),
            discovered_in_run_id=data.get("discovered_in_run_id"),
            generator_model=data.get("generator_model"),
        )
        rel = catalog_api.CatalogAPI.propose_relationship(params)
        return Response(CatalogRelationshipDTOSerializer(instance=rel).data, status=status.HTTP_201_CREATED)

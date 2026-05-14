"""
DRF views for catalog.

Write endpoints the agent uses to populate the semantic graph:
  - POST   /catalog/nodes/             upsert a table/saved-query/system-table node
  - POST   /catalog/columns/           upsert a column under an existing node
  - POST   /catalog/relationships/     propose a relationship between two nodes

Read + review endpoints the UI uses to render the detail page:
  - GET    /catalog/nodes/             list nodes for the team
  - GET    /catalog/nodes/:id/         retrieve a single node with its columns
  - PATCH  /catalog/nodes/:id/         partial update (description, status, tags, ...)
  - GET    /catalog/columns/:id/       retrieve a single column
  - PATCH  /catalog/columns/:id/       partial update of a column's semantic fields
  - GET    /catalog/relationships/:id/ retrieve a single relationship
  - PATCH  /catalog/relationships/:id/ accept / reject / annotate a relationship

Heavy reads still happen via HogQL system tables (`system.tables`, `system.columns`,
`system.relationships`). The REST surface here is for UI-driven editing — narrow and typed.
"""

import asyncio
from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import (
    serializers as drf_serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api as catalog_api
from ..facade.contracts import (
    ProposeRelationshipParams,
    UpdateColumnParams,
    UpdateMetricParams,
    UpdateNodeParams,
    UpdateRelationshipParams,
    UpsertColumnParams,
    UpsertMetricParams,
    UpsertNodeParams,
)
from .serializers import (
    CatalogColumnDTOSerializer,
    CatalogGraphDTOSerializer,
    CatalogMetricDTOSerializer,
    CatalogNodeDTOSerializer,
    CatalogRelationshipDTOSerializer,
    CatalogTraversalRunDTOSerializer,
    ProposeRelationshipInputSerializer,
    UpdateColumnInputSerializer,
    UpdateMetricInputSerializer,
    UpdateNodeInputSerializer,
    UpdateRelationshipInputSerializer,
    UpsertColumnInputSerializer,
    UpsertMetricInputSerializer,
    UpsertNodeInputSerializer,
)


class CatalogSyncResponseSerializer(drf_serializers.Serializer):
    """Response from POST /catalog/sync/. The workflow runs asynchronously —
    callers should poll GET /catalog/runs/ for progress."""

    workflow_id = drf_serializers.CharField(help_text="Temporal workflow id for the kicked-off catalog traversal pass.")


CATALOG_TAG = "catalog"

_NODE_ID_PARAM = OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)


def _reviewer_id(request: Request) -> int | None:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return cast(int, user.pk)


@extend_schema(tags=[CATALOG_TAG])
class CatalogNodeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Catalog nodes — the "table-shaped things" the agent reasons over.

    Idempotent upsert keyed by (team, kind, name): re-posting with the same
    name updates the row in place, so agent traversal runs can re-author
    descriptions safely without piling up duplicates.
    """

    scope_object = "catalog"
    scope_object_read_actions = ["list", "retrieve", "graph"]
    scope_object_write_actions = ["create", "partial_update"]

    @extend_schema(responses={200: CatalogNodeDTOSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all catalog nodes for the team, ordered by business domain then name."""
        nodes = catalog_api.CatalogAPI.list_nodes(cast(int, self.team_id))
        page = self.paginate_queryset(nodes)
        if page is not None:
            return self.get_paginated_response(CatalogNodeDTOSerializer(instance=page, many=True).data)
        return Response(CatalogNodeDTOSerializer(instance=nodes, many=True).data)

    @extend_schema(responses={200: CatalogGraphDTOSerializer})
    @action(detail=False, methods=["get"], pagination_class=None)
    def graph(self, request: Request, **kwargs) -> Response:
        """Return all nodes plus relationships for the team in one payload — drives the graph view."""
        graph = catalog_api.CatalogAPI.get_graph(cast(int, self.team_id))
        return Response(CatalogGraphDTOSerializer(instance=graph).data)

    @extend_schema(parameters=[_NODE_ID_PARAM], responses={200: CatalogNodeDTOSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Retrieve a single catalog node with its columns."""
        node = catalog_api.CatalogAPI.get_node(cast(int, self.team_id), UUID(pk))
        if node is None:
            return Response({"detail": "Node not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogNodeDTOSerializer(instance=node).data)

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

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateNodeInputSerializer,
        responses={200: OpenApiResponse(response=CatalogNodeDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Update editable fields on a catalog node — used by the detail page."""
        data = request.validated_data
        params = UpdateNodeParams(
            team_id=cast(int, self.team_id),
            node_id=UUID(pk),
            name=data.get("name"),
            synthetic_description=data.get("synthetic_description"),
            semantic_role=data.get("semantic_role"),
            business_domain=data.get("business_domain"),
            tags=tuple(data["tags"]) if "tags" in data else None,
            confidence=data.get("confidence"),
            status=data.get("status"),
            reviewed_by_id=_reviewer_id(request),
        )
        node = catalog_api.CatalogAPI.update_node(params)
        if node is None:
            return Response({"detail": "Node not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogNodeDTOSerializer(instance=node).data)


@extend_schema(tags=[CATALOG_TAG])
class CatalogColumnViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Columns under a CatalogNode. Idempotent upsert keyed by (node, name).

    Team isolation is enforced by the parent node — the column's team_id is
    derived from the node's team_id in the facade, not trusted from the request.
    """

    scope_object = "catalog"
    scope_object_read_actions = ["retrieve"]
    scope_object_write_actions = ["create", "partial_update"]

    @extend_schema(parameters=[_NODE_ID_PARAM], responses={200: CatalogColumnDTOSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Retrieve a single column."""
        column = catalog_api.CatalogAPI.get_column(cast(int, self.team_id), UUID(pk))
        if column is None:
            return Response({"detail": "Column not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogColumnDTOSerializer(instance=column).data)

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

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateColumnInputSerializer,
        responses={200: OpenApiResponse(response=CatalogColumnDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Update a column's description, semantic type, PII class, or confidence."""
        data = request.validated_data
        params = UpdateColumnParams(
            team_id=cast(int, self.team_id),
            column_id=UUID(pk),
            synthetic_description=data.get("synthetic_description"),
            semantic_type=data.get("semantic_type"),
            pii_class=data.get("pii_class"),
            confidence=data.get("confidence"),
        )
        column = catalog_api.CatalogAPI.update_column(params)
        if column is None:
            return Response({"detail": "Column not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogColumnDTOSerializer(instance=column).data)


@extend_schema(tags=[CATALOG_TAG])
class CatalogRelationshipViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Edges between catalog nodes.

    Proposals always start in `proposed` status. Confirmed relationships are
    promoted via partial_update by a reviewer.
    Re-proposing the same (source, target, columns, kind) updates confidence
    and reasoning rather than creating a duplicate edge.
    """

    scope_object = "catalog"
    scope_object_read_actions = ["retrieve"]
    scope_object_write_actions = ["create", "partial_update"]

    @extend_schema(parameters=[_NODE_ID_PARAM], responses={200: CatalogRelationshipDTOSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Retrieve a single relationship."""
        rel = catalog_api.CatalogAPI.get_relationship(cast(int, self.team_id), UUID(pk))
        if rel is None:
            return Response({"detail": "Relationship not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogRelationshipDTOSerializer(instance=rel).data)

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

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateRelationshipInputSerializer,
        responses={200: OpenApiResponse(response=CatalogRelationshipDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Accept, reject, or annotate a relationship proposal."""
        data = request.validated_data
        params = UpdateRelationshipParams(
            team_id=cast(int, self.team_id),
            relationship_id=UUID(pk),
            status=data.get("status"),
            confidence=data.get("confidence"),
            reasoning=data.get("reasoning"),
            reviewed_by_id=_reviewer_id(request),
        )
        rel = catalog_api.CatalogAPI.update_relationship(params)
        if rel is None:
            return Response({"detail": "Relationship not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogRelationshipDTOSerializer(instance=rel).data)


@extend_schema(tags=[CATALOG_TAG])
class CatalogMetricViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Semantic metrics — the catalog's "what does this number mean" entries.

    Each metric row is paired 1:1 with a CatalogNode(kind=metric) created in the
    same transaction. The metric row holds the computational definition (an
    EventsNode / DataWarehouseNode / HogQLQuery body); the node carries the
    graph-level metadata (description, status, tags, edges).

    Idempotent on (team, name): re-posting the same name updates description and
    definition without piling up duplicate rows.
    """

    scope_object = "catalog"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "partial_update"]

    @extend_schema(responses={200: CatalogMetricDTOSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all semantic metrics for the team, ordered by name."""
        metrics = catalog_api.CatalogAPI.list_metrics(cast(int, self.team_id))
        page = self.paginate_queryset(metrics)
        if page is not None:
            return self.get_paginated_response(CatalogMetricDTOSerializer(instance=page, many=True).data)
        return Response(CatalogMetricDTOSerializer(instance=metrics, many=True).data)

    @extend_schema(parameters=[_NODE_ID_PARAM], responses={200: CatalogMetricDTOSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Retrieve a single metric with its bound CatalogNode (status, tags, etc.)."""
        metric = catalog_api.CatalogAPI.get_metric(cast(int, self.team_id), UUID(pk))
        if metric is None:
            return Response({"detail": "Metric not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogMetricDTOSerializer(instance=metric).data)

    @validated_request(
        request_serializer=UpsertMetricInputSerializer,
        responses={201: OpenApiResponse(response=CatalogMetricDTOSerializer)},
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Propose a semantic metric and bind its CatalogNode in one call."""
        data = request.validated_data
        params = UpsertMetricParams(
            team_id=cast(int, self.team_id),
            name=data["name"],
            description=data.get("description", ""),
            definition=data["definition"],
            generator_model=data.get("generator_model"),
            confidence=data.get("confidence"),
        )
        metric = catalog_api.CatalogAPI.upsert_metric(params)
        return Response(CatalogMetricDTOSerializer(instance=metric).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateMetricInputSerializer,
        responses={200: OpenApiResponse(response=CatalogMetricDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Update a metric's description or definition. Status/tags live on the bound node — PATCH /catalog/nodes/:node.id/ instead."""
        data = request.validated_data
        params = UpdateMetricParams(
            team_id=cast(int, self.team_id),
            metric_id=UUID(pk),
            description=data.get("description"),
            definition=data.get("definition"),
        )
        metric = catalog_api.CatalogAPI.update_metric(params)
        if metric is None:
            return Response({"detail": "Metric not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogMetricDTOSerializer(instance=metric).data)


@extend_schema(tags=[CATALOG_TAG])
class CatalogTraversalRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Catalog traversal runs — audit rows for each pass of CatalogTraversalWorkflow.

    `list` powers the logs view: a left-rail list of recent runs, each pointing
    at the sandboxed /tasks runs whose streaming logs render inline.
    `sync` kicks off a fresh traversal asynchronously.
    """

    scope_object = "catalog"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["sync"]

    @extend_schema(responses={200: CatalogTraversalRunDTOSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """Return recent catalog traversal runs for the team, newest first."""
        runs = catalog_api.CatalogAPI.list_traversal_runs(cast(int, self.team_id))
        page = self.paginate_queryset(runs)
        if page is not None:
            return self.get_paginated_response(CatalogTraversalRunDTOSerializer(instance=page, many=True).data)
        return Response(CatalogTraversalRunDTOSerializer(instance=runs, many=True).data)

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(response=CatalogSyncResponseSerializer)},
    )
    @action(detail=False, methods=["post"], pagination_class=None)
    def sync(self, request: Request, **kwargs) -> Response:
        """Kick off a catalog traversal asynchronously and return immediately.

        The workflow id is per-team and reusable, so triggering while a run is
        already in-flight is fine — Temporal queues the new run after the
        current one completes.
        """
        workflow_id = asyncio.run(catalog_api.CatalogAPI.start_traversal(cast(int, self.team_id)))
        return Response({"workflow_id": workflow_id}, status=status.HTTP_202_ACCEPTED)

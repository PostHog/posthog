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

from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api as catalog_api
from ..facade.contracts import (
    ProposeRelationshipParams,
    UpdateColumnParams,
    UpdateDimensionParams,
    UpdateEntityParams,
    UpdateMetricParams,
    UpdateNodeParams,
    UpdateRelationshipParams,
    UpsertColumnParams,
    UpsertEntityParams,
    UpsertNodeParams,
)
from ..temporal.activities.agent import start_catalog_clustering_task
from .serializers import (
    CatalogBrowserDTOSerializer,
    CatalogColumnDTOSerializer,
    CatalogDimensionDTOSerializer,
    CatalogEntityDTOSerializer,
    CatalogGraphDTOSerializer,
    CatalogMetricDTOSerializer,
    CatalogNodeDTOSerializer,
    CatalogRelationshipDTOSerializer,
    DeriveResultSerializer,
    ProposeRelationshipInputSerializer,
    UpdateColumnInputSerializer,
    UpdateDimensionInputSerializer,
    UpdateEntityInputSerializer,
    UpdateMetricInputSerializer,
    UpdateNodeInputSerializer,
    UpdateRelationshipInputSerializer,
    UpsertColumnInputSerializer,
    UpsertEntityInputSerializer,
    UpsertNodeInputSerializer,
)

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


# --- Entity / Metric / Dimension viewsets -----------------------------------


@extend_schema(tags=[CATALOG_TAG])
class CatalogEntityViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Business objects — Customer, Order, Subscription. The "folders" in the
    entity-grouped browser. Each entity bundles one or more CatalogNodes that
    represent the same real-world thing across sources, plus the metrics and
    dimensions that hang off it."""

    scope_object = "catalog"
    scope_object_read_actions = ["list", "retrieve", "browser"]
    scope_object_write_actions = ["create", "partial_update", "derive"]
    serializer_class = CatalogEntityDTOSerializer

    @validated_request(
        request_serializer=UpsertEntityInputSerializer,
        responses={201: OpenApiResponse(response=CatalogEntityDTOSerializer)},
    )
    def create(self, request: TypedRequest[dict[str, Any]], **kwargs) -> Response:
        """Upsert a catalog entity by name. The clustering agent calls this for each
        cluster it proposes."""
        data = request.validated_data
        params = UpsertEntityParams(
            team_id=cast(int, self.team_id),
            name=data["name"],
            description=data.get("description"),
            member_node_ids=tuple(data.get("member_node_ids") or ()),
            confidence=data.get("confidence"),
            reasoning=data.get("reasoning", ""),
            generator_model=data.get("generator_model"),
        )
        entity = catalog_api.CatalogAPI.upsert_entity(params)
        return Response(CatalogEntityDTOSerializer(instance=entity).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: CatalogEntityDTOSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all entities for the team."""
        entities = catalog_api.CatalogAPI.list_entities(cast(int, self.team_id))
        page = self.paginate_queryset(entities)
        if page is not None:
            return self.get_paginated_response(CatalogEntityDTOSerializer(instance=page, many=True).data)
        return Response(CatalogEntityDTOSerializer(instance=entities, many=True).data)

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateEntityInputSerializer,
        responses={200: OpenApiResponse(response=CatalogEntityDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Rename, redescribe, or accept/reject an entity."""
        data = request.validated_data
        params = UpdateEntityParams(
            team_id=cast(int, self.team_id),
            entity_id=UUID(pk),
            name=data.get("name"),
            description=data.get("description"),
            status=data.get("status"),
            reviewed_by_id=_reviewer_id(request),
        )
        entity = catalog_api.CatalogAPI.update_entity(params)
        if entity is None:
            return Response({"detail": "Entity not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogEntityDTOSerializer(instance=entity).data)

    @extend_schema(responses={200: CatalogBrowserDTOSerializer})
    @action(detail=False, methods=["get"], pagination_class=None)
    def browser(self, request: Request, **kwargs) -> Response:
        """One-shot fetch for the entity-grouped browser scene: entities,
        metrics, dimensions, and relationships in a single payload."""
        browser = catalog_api.CatalogAPI.get_browser(cast(int, self.team_id))
        return Response(CatalogBrowserDTOSerializer(instance=browser).data)

    @extend_schema(responses={200: DeriveResultSerializer})
    @action(detail=False, methods=["post"], pagination_class=None)
    def derive(self, request: Request, **kwargs) -> Response:
        """Run the rule-based proposer over the current catalog state.

        Idempotent: re-running won't create duplicates because every model
        has a unique constraint on its natural key. Existing rows keep
        their review status."""
        result = catalog_api.CatalogAPI.derive_catalog(cast(int, self.team_id))
        return Response(DeriveResultSerializer(instance=result).data)

    @extend_schema(responses={202: OpenApiResponse(description="Clustering agent task spawned")})
    @action(detail=False, methods=["post"], pagination_class=None)
    def cluster(self, request: Request, **kwargs) -> Response:
        """Kick off the LLM clustering pass.

        Spawns a sandbox agent that reads the catalog state and writes back
        proposed entity groupings via the catalog-entities-create MCP tool.
        Returns the task_run_id so callers can poll for completion if needed —
        but the user-facing flow is fire-and-forget: status changes show up in
        the browser scene when the agent's writes land."""
        task_run_id = start_catalog_clustering_task(cast(int, self.team_id))
        return Response({"task_run_id": task_run_id}, status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=[CATALOG_TAG])
class CatalogMetricViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Metrics — aggregations over a column. SUM(revenue), COUNT(orders), etc."""

    scope_object = "catalog"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["partial_update"]
    serializer_class = CatalogMetricDTOSerializer

    @extend_schema(responses={200: CatalogMetricDTOSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all metrics for the team."""
        metrics = catalog_api.CatalogAPI.list_metrics(cast(int, self.team_id))
        page = self.paginate_queryset(metrics)
        if page is not None:
            return self.get_paginated_response(CatalogMetricDTOSerializer(instance=page, many=True).data)
        return Response(CatalogMetricDTOSerializer(instance=metrics, many=True).data)

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateMetricInputSerializer,
        responses={200: OpenApiResponse(response=CatalogMetricDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Rename, redescribe, reattach to an entity, or accept/reject a metric."""
        data = request.validated_data
        params = UpdateMetricParams(
            team_id=cast(int, self.team_id),
            metric_id=UUID(pk),
            name=data.get("name"),
            description=data.get("description"),
            entity_id=data.get("entity_id"),
            status=data.get("status"),
            reviewed_by_id=_reviewer_id(request),
        )
        metric = catalog_api.CatalogAPI.update_metric(params)
        if metric is None:
            return Response({"detail": "Metric not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogMetricDTOSerializer(instance=metric).data)


@extend_schema(tags=[CATALOG_TAG])
class CatalogDimensionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Dimensions — columns used to group or filter. country, plan_tier, browser."""

    scope_object = "catalog"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["partial_update"]
    serializer_class = CatalogDimensionDTOSerializer

    @extend_schema(responses={200: CatalogDimensionDTOSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List all dimensions for the team."""
        dimensions = catalog_api.CatalogAPI.list_dimensions(cast(int, self.team_id))
        page = self.paginate_queryset(dimensions)
        if page is not None:
            return self.get_paginated_response(CatalogDimensionDTOSerializer(instance=page, many=True).data)
        return Response(CatalogDimensionDTOSerializer(instance=dimensions, many=True).data)

    @extend_schema(parameters=[_NODE_ID_PARAM])
    @validated_request(
        request_serializer=UpdateDimensionInputSerializer,
        responses={200: OpenApiResponse(response=CatalogDimensionDTOSerializer)},
    )
    def partial_update(self, request: TypedRequest[dict[str, Any]], pk: str, **kwargs) -> Response:
        """Rename, redescribe, reattach to an entity, or accept/reject a dimension."""
        data = request.validated_data
        params = UpdateDimensionParams(
            team_id=cast(int, self.team_id),
            dimension_id=UUID(pk),
            name=data.get("name"),
            description=data.get("description"),
            entity_id=data.get("entity_id"),
            status=data.get("status"),
            reviewed_by_id=_reviewer_id(request),
        )
        dimension = catalog_api.CatalogAPI.update_dimension(params)
        if dimension is None:
            return Response({"detail": "Dimension not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(CatalogDimensionDTOSerializer(instance=dimension).data)

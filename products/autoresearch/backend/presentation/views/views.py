"""
DRF views for autoresearch.

Responsibilities:
- Validate incoming JSON (via serializers)
- Call facade functions
- Convert contracts to JSON responses

No business logic here — that lives behind ``facade/api.py``.
"""

from dataclasses import fields
from typing import Any, cast

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.fields import empty
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.autoresearch.backend.facade import api
from products.autoresearch.backend.facade.access import has_autoresearch_access
from products.autoresearch.backend.facade.contracts import PipelineNotFound

from .serializers import AutoresearchPipelineCreateSerializer, AutoresearchPipelineSerializer

logger = structlog.get_logger(__name__)


class FacadePathParamSchema(PostHogAutoSchema):
    """Types a facade-backed viewset's UUID path parameters.

    drf-spectacular reads a path parameter's type off the viewset's ``queryset`` model. These
    viewsets reach their data through the facade and declare no queryset, so each id is spelled
    out here instead. Declaring them through ``@extend_schema`` would not work: that appends the
    parameter to every operation in the viewset, including the collection routes whose path has
    no id in it. This hook only ever sees variables the path actually contains.
    """

    def _resolve_path_parameters(self, variables: Any) -> Any:
        declared = getattr(self.view, "uuid_path_parameters", {})
        resolved = []
        for parameter in super()._resolve_path_parameters(variables):
            description = declared.get(parameter["name"])
            if parameter["name"] not in declared:
                resolved.append(parameter)
                continue
            # Rebuilt rather than mutated, so the keys keep the order drf-spectacular emits.
            rebuilt: dict[str, Any] = {}
            for key, value in parameter.items():
                if key == "schema":
                    rebuilt["schema"] = {"type": "string", "format": "uuid"}
                    if description:
                        rebuilt["description"] = description
                elif key == "description" and description:
                    continue
                else:
                    rebuilt[key] = value
            resolved.append(rebuilt)
        return resolved


class AutoresearchAccessPermission(BasePermission):
    """Gate the autoresearch product behind the `autoresearch` feature flag."""

    message = "Autoresearch is not enabled for this team."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_id = getattr(view, "team_id", None)
        return has_autoresearch_access(request.user, team_id=team_id)


class _FacadePaginationMixin:
    # Drives the standard ``LimitOffsetPagination`` envelope from a facade ``(page, count)``
    # result. The facade does the slicing, so the paginator's state is set directly rather than
    # handed a queryset — keeping the param names, default page size, and ``count`` / ``next`` /
    # ``previous`` shape identical to the model-backed viewsets.
    def _paginate_via_facade(self, request: Request, fetch: Any, serializer_class: Any) -> Response:
        paginator = self.paginator  # type: ignore[attr-defined]
        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)
        page, count = fetch(offset=offset, limit=limit)
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        serializer = serializer_class(instance=page, many=True)
        return paginator.get_paginated_response(serializer.data)


def _pipeline_write_fields(validated: Any) -> dict[str, Any]:
    """The fields to persist.

    ``validated`` is the write contract, where a field the request body did not carry is left as
    the ``empty`` sentinel. Skipping those is what stops a PATCH writing a default over a field
    the caller never mentioned; the values ``validate()`` derived are real, so they carry through.
    """
    return {
        f.name: getattr(validated, f.name) for f in fields(validated) if getattr(validated, f.name, empty) is not empty
    }


@extend_schema(tags=["autoresearch"])
class AutoresearchPipelineViewSet(TeamAndOrgViewSetMixin, _FacadePaginationMixin, viewsets.ModelViewSet):
    """
    Manage autoresearch prediction pipelines.

    A pipeline defines a target event, population, and horizon. The autoresearch
    training loop finds the best predictive recipe; the inference workflow scores
    users daily and emits autoresearch_prediction events.
    """

    schema = FacadePathParamSchema()
    uuid_path_parameters = {"id": "A UUID string identifying this autoresearch pipeline."}
    scope_object = "autoresearch"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy"]
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchPipelineSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def get_serializer_class(self) -> type[AutoresearchPipelineSerializer | AutoresearchPipelineCreateSerializer]:
        if self.action in ("create", "partial_update", "update"):
            return AutoresearchPipelineCreateSerializer
        return AutoresearchPipelineSerializer

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_pipelines(self.team_id, offset=offset, limit=limit),
            AutoresearchPipelineSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            pipeline = api.get_pipeline(self.team_id, self.kwargs["pk"])
        except PipelineNotFound:
            raise NotFound("Pipeline not found.")
        return Response(AutoresearchPipelineSerializer(instance=pipeline).data)

    @extend_schema(
        request=AutoresearchPipelineCreateSerializer,
        # `create` responds with the read serializer, not the write one. Without this,
        # drf-spectacular infers the response from `get_serializer_class()` and the
        # generated client loses `id` — which `enrich_url: '{id}'` needs.
        responses={201: AutoresearchPipelineSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AutoresearchPipelineCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        pipeline = api.create_pipeline(
            self.team_id,
            fields=_pipeline_write_fields(serializer.validated_data),
            created_by=cast(User, request.user),
        )
        output = AutoresearchPipelineSerializer(instance=pipeline)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=201, headers=headers)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        context = {**self.get_serializer_context(), "pipeline_id": self.kwargs["pk"]}
        serializer = AutoresearchPipelineCreateSerializer(data=request.data, partial=partial, context=context)
        serializer.is_valid(raise_exception=True)
        try:
            pipeline = api.update_pipeline(
                self.team_id,
                self.kwargs["pk"],
                fields=_pipeline_write_fields(serializer.validated_data),
            )
        except PipelineNotFound:
            raise NotFound("Pipeline not found.")
        return Response(AutoresearchPipelineSerializer(instance=pipeline).data)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            api.delete_pipeline(self.team_id, self.kwargs["pk"])
        except PipelineNotFound:
            raise NotFound("Pipeline not found.")
        return Response(status=204)

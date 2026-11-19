"""
DRF views for dashboards_v2.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from typing import Any

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict

from ..facade import api
from ..facade.contracts import (
    CreateDashboardV2Input,
    DashboardV2Detail,
    DashboardV2NotFoundError,
    DashboardV2UidTakenError,
    DashboardV2VersionConflictError,
    UpdateDashboardV2Input,
)
from ..facade.spec import SpecValidationError
from .serializers import (
    CreateDashboardV2InputSerializer,
    DashboardV2DetailSerializer,
    DashboardV2InvalidSpecErrorSerializer,
    DashboardV2SummarySerializer,
    UpdateDashboardV2InputSerializer,
)

_INVALID_SPEC_RESPONSE = OpenApiResponse(
    response=DashboardV2InvalidSpecErrorSerializer,
    description="The request body or the spec is not valid. For a spec, `extra.issues` lists every problem.",
)
_NOT_FOUND_RESPONSE = OpenApiResponse(description="No dashboard in this project has this uid.")
_SEARCH_PARAMETER = OpenApiParameter(
    "search", str, description="Return only dashboards whose title contains this text, ignoring case."
)


class InvalidSpecError(serializers.ValidationError):
    def __init__(self, error: SpecValidationError) -> None:
        super().__init__({"spec": f"The spec is not valid. {error}"}, code="invalid_spec")
        # drf-exceptions-hog adds `extra` to the error body.
        self.extra = {"issues": [issue.model_dump() for issue in error.issues]}


class DashboardV2ViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Dashboards stored as one JSON document."""

    scope_object = "dashboard"
    # Access rules on `dashboard` name rows of the dashboards product, never these, so only resource access applies.
    records_have_object_access_rules = False
    requires_resource_level_access = True

    serializer_class = DashboardV2DetailSerializer
    pagination_class = FacadeLimitOffsetPagination
    lookup_field = "uid"
    path_parameters = {"uid": PathParameter(type=str, description="The `uid` of the dashboard.")}

    def read_object(self) -> DashboardV2Detail | None:
        try:
            return api.get_dashboard(self.team_id, self.kwargs["uid"])
        except DashboardV2NotFoundError:
            return None

    @extend_schema(parameters=[_SEARCH_PARAMETER], responses={200: DashboardV2SummarySerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List the dashboards of the project, the most recently saved first. Rows do not include the spec."""
        search = request.query_params.get("search")
        return facade_page_response(
            self,
            lambda page: api.list_dashboards(self.team_id, page, search=search),
            serializer_class=DashboardV2SummarySerializer,
        )

    @validated_request(
        request_serializer=CreateDashboardV2InputSerializer,
        responses={
            201: OpenApiResponse(response=DashboardV2DetailSerializer),
            400: _INVALID_SPEC_RESPONSE,
            409: OpenApiResponse(description="A dashboard in this project already has the uid of the spec."),
        },
    )
    def create(self, request: TypedRequest[CreateDashboardV2Input], **kwargs: Any) -> Response:
        """Create a dashboard from a spec. The dashboard starts at version 1."""
        try:
            dashboard = api.create_dashboard(self.team_id, request.user.id, request.validated_data)
        except SpecValidationError as error:
            raise InvalidSpecError(error)
        except DashboardV2UidTakenError as error:
            raise Conflict(
                f'A dashboard with the uid "{error.uid}" already exists in this project. Use another uid.',
                code="uid_taken",
            )
        return Response(DashboardV2DetailSerializer(dashboard).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: DashboardV2DetailSerializer, 404: _NOT_FOUND_RESPONSE})
    def retrieve(self, request: Request, uid: str, **kwargs: Any) -> Response:
        """Get a dashboard with its spec."""
        return Response(DashboardV2DetailSerializer(self.get_object()).data)

    @validated_request(
        request_serializer=UpdateDashboardV2InputSerializer,
        responses={
            200: OpenApiResponse(response=DashboardV2DetailSerializer),
            400: _INVALID_SPEC_RESPONSE,
            404: _NOT_FOUND_RESPONSE,
            409: OpenApiResponse(description="The dashboard is not at `base_version`. Nothing was saved."),
        },
    )
    def update(self, request: TypedRequest[UpdateDashboardV2Input], uid: str, **kwargs: Any) -> Response:
        """Save a spec as the next version of a dashboard. The uid of a dashboard cannot change."""
        self.get_object()
        try:
            dashboard = api.update_dashboard(self.team_id, uid, request.user.id, request.validated_data)
        except SpecValidationError as error:
            raise InvalidSpecError(error)
        except DashboardV2NotFoundError:
            raise NotFound()
        except DashboardV2VersionConflictError as error:
            raise Conflict(
                f"The dashboard is at version {error.current_version}, and this save is based on version "
                f"{error.base_version}. Load the dashboard again, then make the change on the new version.",
                code="version_conflict",
            )
        return Response(DashboardV2DetailSerializer(dashboard).data)

    @extend_schema(responses={204: None, 404: _NOT_FOUND_RESPONSE})
    def destroy(self, request: Request, uid: str, **kwargs: Any) -> Response:
        """Delete a dashboard. Its uid can then be used for a new dashboard."""
        self.get_object()
        try:
            api.delete_dashboard(self.team_id, uid)
        except DashboardV2NotFoundError:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

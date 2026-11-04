from collections.abc import Callable
from datetime import datetime
from typing import cast

from django.http import Http404

from drf_spectacular.utils import extend_schema
from rest_framework import filters, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import is_service_auth

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.annotations.backend.facade import api, contracts
from products.annotations.backend.facade.enums import AnnotationScope

from ..serializers import AnnotationSerializer

_TRUTHY_PARAM_VALUES = ("true", "1", "yes")


class AnnotationsLimitOffsetPagination(FacadeLimitOffsetPagination):
    default_limit = 1000


def _parse_date_param(value: str, name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise serializers.ValidationError(f"Invalid date range: {name} must be a valid ISO 8601 date")


def _raise_for_rejection(write: Callable[[], contracts.Annotation]) -> contracts.Annotation:
    """Run a facade write, and answer a rejected one the way a serializer's validate() would."""
    try:
        return write()
    except contracts.AnnotationNotFoundError:
        raise Http404("No Annotation matches the given query.")
    except contracts.AnnotationWriteRejectedError as rejected:
        field = "dashboard_item" if rejected.field == "insight_id" else rejected.field
        raise serializers.ValidationError(as_serializer_error(serializers.ValidationError({field: rejected.message})))


class AnnotationsViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    """
    Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
    """

    scope_object = "annotation"
    path_parameters = {
        "pk": PathParameter(type=int, description="A unique integer value identifying this annotation."),
    }
    serializer_class = AnnotationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["content"]
    pagination_class = AnnotationsLimitOffsetPagination

    def _filters(self) -> contracts.AnnotationFilters:
        """The query params narrow every route, including a retrieve or an update."""
        params = self.request.query_params

        scope = params.get("scope")
        if scope:
            # let's allow the more recently used "insight" scope to be used as "dashboard_item"
            scope = "dashboard_item" if scope == "insight" else scope
            if scope not in AnnotationScope.values:
                raise serializers.ValidationError(f"Invalid scope: {scope}")

        date_from = params.get("date_from")
        date_to = params.get("date_to")
        date_from_parsed = _parse_date_param(date_from, "date_from") if date_from else None
        date_to_parsed = _parse_date_param(date_to, "date_to") if date_to else None
        if date_from_parsed and date_to_parsed and date_from_parsed > date_to_parsed:
            raise serializers.ValidationError("Invalid date range: date_from must be before date_to")

        hidden = params.get("hidden_in_user_interface")
        return contracts.AnnotationFilters(
            scope=AnnotationScope(scope) if scope else None,
            date_from=date_from_parsed,
            date_to=date_to_parsed,
            hidden_in_user_interface=None if hidden is None else hidden.lower() in _TRUTHY_PARAM_VALUES,
            search_terms=tuple(filters.SearchFilter().get_search_terms(self.request)),
        )

    def _list_access(self) -> contracts.AnnotationAccess | None:
        """The access control narrowing a queryset list gets from TeamAndOrgViewSetMixin, with the same gates."""
        if is_service_auth(self.request):
            return None
        access = self.user_access_control.list_access_filter(
            "annotation", include_all_if_admin=self.request.GET.get("admin_include_all") == "true"
        )
        if access is None:
            return None
        return contracts.AnnotationAccess(
            viewer_id=cast(User, self.request.user).id,
            only_allowed=access.only_allowed,
            allowed_ids=access.allowed_ids,
            blocked_ids=access.blocked_ids,
        )

    def _get_annotation(self, *, include_deleted: bool) -> contracts.Annotation:
        try:
            annotation = api.get_annotation(
                team_id=self.team.id,
                organization_id=self.team.organization_id,
                annotation_id=self.kwargs["pk"],
                filters=self._filters(),
                include_deleted=include_deleted,
            )
        except contracts.AnnotationNotFoundError:
            raise Http404("No Annotation matches the given query.")
        # An organization-scoped annotation can belong to a sibling project. Its access is checked
        # against the rules of the project it is read from.
        self.check_object_permissions(
            self.request,
            ObjectAccessRef(
                resource="annotation",
                id=str(annotation.id),
                team_id=self.team.id,
                created_by_id=annotation.created_by_id,
            ),
        )
        return annotation

    @extend_schema(responses={200: AnnotationSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        annotation_filters = self._filters()
        access = self._list_access()
        return facade_page_response(
            self,
            lambda page: api.list_annotations(
                team_id=self.team.id,
                organization_id=self.team.organization_id,
                filters=annotation_filters,
                page=page,
                access=access,
            ),
        )

    @extend_schema(responses={200: AnnotationSerializer})
    def retrieve(self, request: Request, pk: int, **kwargs) -> Response:
        return Response(self.get_serializer(self._get_annotation(include_deleted=False)).data)

    @extend_schema(request=AnnotationSerializer, responses={201: AnnotationSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = AnnotationSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        annotation = _raise_for_rejection(
            lambda: api.create_annotation(
                team_id=self.team.id,
                organization_id=self.team.organization_id,
                created_by_id=cast(User, request.user).id,
                write=serializer.to_write(),
            )
        )
        return Response(self.get_serializer(annotation).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AnnotationSerializer, responses={200: AnnotationSerializer})
    def update(self, request: Request, pk: int, **kwargs) -> Response:
        return self._update(request, partial=False)

    @extend_schema(request=AnnotationSerializer, responses={200: AnnotationSerializer})
    def partial_update(self, request: Request, pk: int, **kwargs) -> Response:
        return self._update(request, partial=True)

    def _update(self, request: Request, *, partial: bool) -> Response:
        # A soft-deleted annotation is restored with a PATCH that sets `deleted` to false, so only a
        # partial update can reach one.
        annotation = self._get_annotation(include_deleted=partial)
        serializer = AnnotationSerializer(
            annotation, data=request.data, partial=partial, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        updated = _raise_for_rejection(
            lambda: api.update_annotation(
                team_id=self.team.id,
                organization_id=self.team.organization_id,
                annotation_id=annotation.id,
                write=serializer.to_write(),
                include_deleted=partial,
            )
        )
        return Response(self.get_serializer(updated).data)

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from django.core.exceptions import ImproperlyConfigured

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.response import Response

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest
from posthog.api.pagination import FacadeLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User
from posthog.paging import Page, PageRequest

from ...facade import api, contracts, diagnostics
from ..query_concurrency import query_concurrency_slots
from .list_filters import require_query_scope_for_filters, selection_filters
from .property_filters import QUERY_SCOPE
from .trace_resource import TraceResourceSchema

DIAGNOSTICS_PAGE_DEFAULT_LIMIT: Final = 50
MALFORMED_KEY = "This key isn't valid. Use a key from the list."
UNKNOWN_KEY = "Nothing with this key occurred in the date range."
RANGE_TOO_LONG_RESPONSE = OpenApiResponse(response=contracts.TraceMetricsRangeTooLong)
SCOPE_RESPONSE = OpenApiResponse(
    description=f"The key lacks a required scope, or a property filter needs the {QUERY_SCOPE} scope."
)


def entity_key_parameter(entity: str, list_name: str) -> OpenApiParameter:
    return OpenApiParameter(
        "id",
        OpenApiTypes.STR,
        OpenApiParameter.PATH,
        description=f"The {entity}'s key, as the {list_name} list hands it out.",
    )


class DiagnosticsPage[Item](Protocol):
    @property
    def page(self) -> Page[Item]: ...
    @property
    def counts(self) -> contracts.Contract: ...
    @property
    def bucket_starts(self) -> list[datetime]: ...
    @property
    def nothing_captured(self) -> bool: ...
    @property
    def order(self) -> StrEnum: ...


class DiagnosticsPagination(FacadeLimitOffsetPagination):
    default_limit = DIAGNOSTICS_PAGE_DEFAULT_LIMIT
    max_limit = diagnostics.DIAGNOSTICS_PAGE_MAX_LIMIT


class DiagnosticsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The errors and tools of a trace selection, each read inside the team's query slot."""

    scope_object = "llm_analytics"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions: list[str] = []
    # Errors and tools are project-wide data, so a grant on a single llm_analytics object must not open them.
    requires_resource_level_access = True
    serializer_class = _FallbackSerializer
    pagination_class = DiagnosticsPagination
    # A list's contract already carries the page fields, so the schema must not wrap it in a second page. Its query
    # serializer declares `limit` and `offset` instead.
    schema = TraceResourceSchema()
    not_found_errors: tuple[type[Exception], ...] = ()
    bad_request_errors: tuple[type[Exception], ...] = (
        api.InvalidTraceWindowError,
        api.InvalidTraceSelectionError,
        ExposedHogQLError,
        ExposedCHQueryError,
    )

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, diagnostics.DiagnosticsRangeTooLongError):
            return Response(
                contracts.TraceMetricsRangeTooLong().model_dump(), status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        if isinstance(exc, diagnostics.MalformedEntityKeyError):
            return Response({"detail": MALFORMED_KEY}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, self.bad_request_errors):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, self.not_found_errors):
            return Response({"detail": UNKNOWN_KEY}, status=status.HTTP_404_NOT_FOUND)
        return super().handle_exception(exc)

    def _read[T](self, request: ValidatedRequest, read: Callable[[User | None], T]) -> T:
        tag_queries(feature=Feature.QUERY)
        user = request.user if isinstance(request.user, User) else None
        with query_concurrency_slots(self.team):
            return read(user)

    def _selection(self, request: ValidatedRequest) -> api.TraceSelection:
        query = request.validated_query_data
        require_query_scope_for_filters(request, query)
        return api.TraceSelection(
            window=api.resolve_trace_window(self.team, query.get("date_from"), query.get("date_to")),
            include_support_traces=is_impersonated(request),
            **selection_filters(query),
        )

    def _page_response[Item](
        self,
        request: ValidatedRequest,
        load: Callable[[User | None, PageRequest], Callable[[], DiagnosticsPage[Item]]],
        contract: Callable[..., contracts.Contract],
    ) -> Response:
        """Serves the page `load` builds as the `contract` list, its extras beside the page fields."""
        paginator = self.paginator
        if not isinstance(paginator, FacadeLimitOffsetPagination):
            raise ImproperlyConfigured(f"{type(self).__name__} needs a FacadeLimitOffsetPagination pagination_class.")
        built: list[DiagnosticsPage[Item]] = []

        def fetch(page: PageRequest) -> Page[Item]:
            build = self._read(request, lambda user: load(user, page))
            # Built after the query slot is released, so building a page never holds the team's slot.
            built.append(build())
            return built[0].page

        page = paginator.read_facade_page(request, fetch)
        [extras] = built
        body = contract(
            **paginator.get_paginated_response(page.results).data,
            counts=extras.counts,
            bucket_starts=extras.bucket_starts,
            nothing_captured=extras.nothing_captured,
            order=extras.order,
        )
        return Response(body.model_dump(mode="json", by_alias=True))

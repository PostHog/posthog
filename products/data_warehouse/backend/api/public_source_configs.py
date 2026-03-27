from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import SourceConfig

from posthog.temporal.data_imports.sources import SourceRegistry


@extend_schema(tags=["data_warehouse"])
class PublicSourceConfigViewSet(viewsets.ViewSet):
    """
    Public (unauthenticated) endpoint that returns the full SourceConfig
    for every registered data warehouse import source — including the
    input field schemas needed to render setup forms.

    This is the data-warehouse equivalent of ``/api/public_hog_function_templates``.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: dict[str, SourceConfig]},
        description="Returns a map of source type identifiers to their full SourceConfig.",
    )
    def list(self, request: Request) -> Response:
        sources = SourceRegistry.get_all_sources()

        results = {str(source_type): source.get_source_config.model_dump() for source_type, source in sources.items()}

        return Response(status=status.HTTP_200_OK, data=results)

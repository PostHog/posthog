from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.temporal.data_imports.sources import SourceRegistry


class PublicSourceConfigSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Source type identifier (e.g. 'Stripe', 'Postgres').")
    label = serializers.CharField(allow_null=True, help_text="Display label for the source.")
    icon_path = serializers.CharField(source="iconPath", help_text="Path to the source's icon.")
    caption = serializers.CharField(allow_null=True, help_text="Short description of the source.")
    docs_url = serializers.CharField(allow_null=True, help_text="Link to the source's documentation.")
    beta_source = serializers.BooleanField(
        allow_null=True, source="betaSource", help_text="Whether this source is in beta."
    )
    unreleased_source = serializers.BooleanField(
        allow_null=True, source="unreleasedSource", help_text="Whether this source is unreleased."
    )
    featured = serializers.BooleanField(
        allow_null=True, help_text="Whether this source should be prominently displayed."
    )


@extend_schema(tags=["data_warehouse"])
class PublicSourceConfigViewSet(viewsets.ViewSet):
    """
    Public (unauthenticated) endpoint that returns metadata about available
    data warehouse import sources — name, label, icon, docs URL, and status flags.

    This is the data-warehouse equivalent of ``/api/public_hog_function_templates``.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = PublicSourceConfigSerializer

    def list(self, request: Request) -> Response:
        sources = SourceRegistry.get_all_sources()

        results = []
        for _source_type, source in sources.items():
            config = source.get_source_config
            results.append(
                {
                    "name": str(config.name.value) if config.name else None,
                    "label": config.label,
                    "iconPath": config.iconPath,
                    "caption": config.caption,
                    "docsUrl": config.docsUrl,
                    "betaSource": config.betaSource,
                    "unreleasedSource": config.unreleasedSource,
                    "featured": config.featured,
                }
            )

        # Sort alphabetically by label for stable ordering
        results.sort(key=lambda s: (s.get("label") or s.get("name") or "").lower())

        return Response(status=status.HTTP_200_OK, data=results)

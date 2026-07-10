import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import SourceConfig

from products.warehouse_sources.backend.facade.source_management import SourceRegistry

logger = structlog.get_logger(__name__)


def build_source_configs() -> dict[str, dict]:
    """Build the source-config catalog returned by both the public endpoint and the wizard.

    Each entry is the source's ``SourceConfig`` augmented with ``supportsColumnSelection`` and a
    credential-free ``tables`` catalog (empty for SQL/file sources with user-defined schemas). Kept
    in one place so the two endpoints can never drift (see ``test_matches_wizard_response``).
    """
    sources = SourceRegistry.get_all_sources()

    results: dict[str, dict] = {}
    for source_type, source in sources.items():
        config = source.get_source_config.model_dump()
        config["supportsColumnSelection"] = bool(source.supports_column_selection)
        config["versions"] = list(source.supported_versions)
        config["defaultVersion"] = source.default_version
        config["apiDocsUrl"] = source.api_docs_url
        config["deprecatedVersions"] = [
            {"version": d.version, "sunsetAt": d.sunset_at.isoformat() if d.sunset_at else None}
            for d in source.deprecated_versions
        ]
        # Per-source guard: a single misbehaving source must never break the whole catalog.
        try:
            config["tables"] = source.get_documented_tables()
        except Exception:
            logger.exception("build_source_configs: get_documented_tables failed", source_type=str(source_type))
            config["tables"] = []
        results[str(source_type)] = config

    return results


class PublicSourceConfigViewSet(viewsets.ViewSet):
    """
    Public (unauthenticated) endpoint that returns the full SourceConfig
    for every registered data warehouse import source — including the
    input field schemas needed to render setup forms and, for fixed-schema
    sources, the documented table catalog rendered on posthog.com docs.

    This is the data-warehouse equivalent of ``/api/public_hog_function_templates``.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: dict[str, SourceConfig]},
        description=(
            "Returns a map of source type identifiers to their full SourceConfig. Each entry is "
            "augmented with `supportsColumnSelection` and a `tables` array (the credential-free "
            "documented table catalog; empty for SQL/file sources with user-defined schemas)."
        ),
    )
    def list(self, request: Request) -> Response:
        # Results are deploy-static (they only change when source code ships), so this is a
        # safe candidate for caching if the endpoint ever gets hot; today it is fetched only
        # at posthog.com build time.
        return Response(status=status.HTTP_200_OK, data=build_source_configs())

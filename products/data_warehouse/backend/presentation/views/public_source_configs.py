import functools

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import SourceConfig

from products.warehouse_sources.backend.facade.source_management import SourceRegistry

logger = structlog.get_logger(__name__)


@functools.cache
def build_source_configs(*, include_tables: bool = True, include_unreleased: bool = True) -> dict[str, dict]:
    """Build the source-config catalog returned by both the public endpoint and the wizard.

    Each entry is the source's ``SourceConfig`` augmented with ``supportsColumnSelection`` and,
    when ``include_tables`` is set, a credential-free ``tables`` catalog (empty for SQL/file
    sources with user-defined schemas). ``tables`` exists for the posthog.com docs build; the
    in-app wizard skips it because nothing in the app reads it and it is ~40% of the payload.
    Kept in one place so the two endpoints can never drift (see ``test_matches_wizard_response``).

    When ``include_unreleased`` is false, sources marked ``unreleasedSource`` are omitted. The
    authenticated wizard keeps them so the app can render "coming soon" entries; the public,
    unauthenticated catalog drops them so unreleased connector metadata isn't disclosed early.

    The catalog is deploy-static (it only changes when source code ships), so the result is
    memoized per process — callers must treat it as read-only.
    """
    sources = SourceRegistry.get_all_sources()

    results: dict[str, dict] = {}
    for source_type, source in sources.items():
        source_config = source.get_source_config
        if not include_unreleased and source_config.unreleasedSource:
            continue
        config = source_config.model_dump()
        config["supportsColumnSelection"] = bool(source.supports_column_selection)
        config["versions"] = list(source.supported_versions)
        config["defaultVersion"] = source.default_version
        config["apiDocsUrl"] = source.api_docs_url
        config["deprecatedVersions"] = [
            {"version": d.version, "sunsetAt": d.sunset_at.isoformat() if d.sunset_at else None}
            for d in source.deprecated_versions
        ]
        if include_tables:
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
            "augmented with `supportsColumnSelection`, a `tables` array (the credential-free "
            "documented table catalog; empty for SQL/file sources with user-defined schemas), and "
            "vendor API version metadata: `versions` (supported version labels), `defaultVersion`, "
            "`apiDocsUrl` (vendor API docs/changelog URL or null), and `deprecatedVersions` "
            "(array of `{version, sunsetAt}` with `sunsetAt` an ISO date or null)."
        ),
    )
    def list(self, request: Request) -> Response:
        # Results are deploy-static (they only change when source code ships), so this is a
        # safe candidate for caching if the endpoint ever gets hot; today it is fetched only
        # at posthog.com build time. Unreleased sources are excluded so their connector
        # metadata isn't disclosed to unauthenticated callers before release.
        return Response(status=status.HTTP_200_OK, data=build_source_configs(include_unreleased=False))

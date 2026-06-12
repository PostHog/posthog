from typing import Optional, cast

import structlog

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import WebflowSourceConfig
from posthog.temporal.data_imports.sources.webflow.settings import COLLECTION_SCHEMA_PREFIX, STATIC_ENDPOINTS
from posthog.temporal.data_imports.sources.webflow.webflow import (
    WebflowResumeConfig,
    list_collections,
    validate_credentials as validate_webflow_credentials,
    webflow_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@SourceRegistry.register
class WebflowSource(ResumableSource[WebflowSourceConfig, WebflowResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WEBFLOW

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Webflow API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your Webflow API token is missing a required scope. Grant the read scopes for the resources you want to sync and reconnect.",
        }

    def get_schemas(
        self,
        config: WebflowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Webflow has no verified server-side timestamp range filter on its list
        # endpoints (the createdOn/lastUpdated query params are exact-match, not
        # ranges), so every endpoint is full-refresh only for now.
        schemas = [
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in STATIC_ENDPOINTS
        ]

        # Each site exposes a different set of CMS collections, so discover them
        # dynamically and expose one schema per collection. Best-effort: if the
        # token can't list collections (missing scope, transient error) we still
        # return the static endpoints rather than failing the whole source.
        try:
            for collection in list_collections(config.api_token, config.site_id):
                slug = collection.get("slug")
                if not slug:
                    continue
                schemas.append(
                    SourceSchema(
                        name=f"{COLLECTION_SCHEMA_PREFIX}{slug}",
                        supports_incremental=False,
                        supports_append=False,
                        incremental_fields=[],
                        label=collection.get("displayName"),
                    )
                )
        except Exception as e:
            # Best-effort: a missing scope, transient network error, or schema-discovery
            # bug shouldn't fail the whole source. Log so the cause is debuggable.
            logger.debug("Webflow: failed to discover CMS collections, returning static endpoints only", exc_info=e)

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: WebflowSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_webflow_credentials(config.api_token, config.site_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WebflowResumeConfig]:
        return ResumableSourceManager[WebflowResumeConfig](inputs, WebflowResumeConfig)

    def source_for_pipeline(
        self,
        config: WebflowSourceConfig,
        resumable_source_manager: ResumableSourceManager[WebflowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return webflow_source(
            api_token=config.api_token,
            site_id=config.site_id,
            schema_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WEBFLOW,
            label="Webflow",
            caption="""Enter your Webflow v2 API token and Site ID to pull your Webflow site data into the PostHog Data warehouse.

Create a **Site API token** in Webflow under **Site settings → Apps & integrations → API access**, and copy the **Site ID** from the same page (or from your site's URL in the Designer).

Grant the read scopes for the resources you want to sync:
- `sites:read`
- `cms:read` (collections and collection items)
- `ecommerce:read` (products and orders)
- `pages:read`
- `users:read`
- `forms:read`
""",
            iconPath="/static/services/webflow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/webflow",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="site_id",
                        label="Site ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

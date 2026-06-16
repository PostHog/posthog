from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.cloudflare.cloudflare import (
    cloudflare_source,
    validate_credentials as validate_cloudflare_credentials,
)
from posthog.temporal.data_imports.sources.cloudflare.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import CloudflareSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudflareSource(SimpleSource[CloudflareSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.cloudflare.com": "Cloudflare authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://api.cloudflare.com": "Cloudflare denied access. Please check that your API token has read permissions for this resource.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDFLARE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cloudflare",
            caption="""Enter your Cloudflare API token to pull your Cloudflare configuration data into the PostHog Data warehouse.

Create an API token in the [Cloudflare dashboard](https://dash.cloudflare.com/profile/api-tokens) with read permissions for Account Settings, Zone, and DNS. DNS records are synced from every zone the token can access.""",
            iconPath="/static/services/cloudflare.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudflare",
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
                ],
            ),
        )

    def get_schemas(
        self,
        config: CloudflareSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # v4 REST lists are small configuration tables with no updated-since
        # filters; the analytics datasets live in the GraphQL API (follow-up).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CloudflareSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_cloudflare_credentials(config.api_token):
            return True, None

        return False, "Invalid Cloudflare API token"

    def source_for_pipeline(self, config: CloudflareSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cloudflare_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )

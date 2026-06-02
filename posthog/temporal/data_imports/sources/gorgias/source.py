from typing import Optional, cast

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
from posthog.temporal.data_imports.sources.generated_configs import GorgiasSourceConfig
from posthog.temporal.data_imports.sources.gorgias.gorgias import (
    GorgiasResumeConfig,
    gorgias_source,
    validate_credentials as validate_gorgias_credentials,
)
from posthog.temporal.data_imports.sources.gorgias.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GorgiasSource(ResumableSource[GorgiasSourceConfig, GorgiasResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GORGIAS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Gorgias authentication failed. Check your email and API key.",
            "403 Client Error: Forbidden for url": "Your Gorgias API key does not have access to this resource. Check the integration's permissions.",
            "Unauthorized for url": "Gorgias authentication failed. Check your email and API key.",
        }

    def get_schemas(
        self,
        config: GorgiasSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Gorgias list endpoints have no server-side timestamp filter (only client-side
        # ordering), so every endpoint is full-refresh only. Cursor pagination still lets
        # an interrupted sync resume mid-stream via the ResumableSourceManager.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GorgiasSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gorgias_credentials(config.gorgias_domain, config.email, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GorgiasResumeConfig]:
        return ResumableSourceManager[GorgiasResumeConfig](inputs, GorgiasResumeConfig)

    def source_for_pipeline(
        self,
        config: GorgiasSourceConfig,
        resumable_source_manager: ResumableSourceManager[GorgiasResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gorgias_source(
            domain=config.gorgias_domain,
            email=config.email,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GORGIAS,
            label="Gorgias",
            caption="""Enter your Gorgias credentials to pull your helpdesk data into the PostHog Data warehouse.

Create an API key in your Gorgias account under **Settings → REST API**. Use the email of the account that owns the key together with the key itself.

This source authenticates with HTTP Basic Auth (email + API key) and requires read access to the endpoints you want to sync (tickets, messages, customers, users, satisfaction surveys, tags, views, teams, macros).""",
            iconPath="/static/services/gorgias.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gorgias",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="gorgias_domain",
                        label="Gorgias domain (subdomain)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-company",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="email",
                        label="Account email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@your-company.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

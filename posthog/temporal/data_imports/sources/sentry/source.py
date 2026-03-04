from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SentrySourceConfig
from posthog.temporal.data_imports.sources.sentry.sentry import (
    sentry_source,
    validate_credentials as validate_sentry_credentials,
)
from posthog.temporal.data_imports.sources.sentry.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SentrySource(SimpleSource[SentrySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENTRY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SENTRY,
            label="Sentry",
            iconPath="/static/services/sentry.png",
            caption="""Enter a Sentry auth token and your organization slug to sync projects and issues.

Create a token in Sentry and make sure it includes:
- `org:read`
- `event:read`
""",
            docsUrl="https://docs.sentry.io/api/",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sntrys_...",
                    ),
                    SourceFieldInputConfig(
                        name="organization_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-org",
                    ),
                    SourceFieldInputConfig(
                        name="api_base_url",
                        label="API base URL",
                        type=SourceFieldInputConfigType.URL,
                        required=False,
                        placeholder="https://sentry.io",
                        caption="Optional. Use for regional domains like https://us.sentry.io or https://de.sentry.io.",
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Sentry auth token. Please update your token and reconnect.",
            "403 Client Error": "Sentry token is missing required scopes. Please add org:read and event:read.",
            "404 Client Error": "Sentry organization not found. Verify your organization slug.",
        }

    def get_schemas(self, config: SentrySourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: SentrySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_sentry_credentials(
            auth_token=config.auth_token,
            organization_slug=config.organization_slug,
            api_base_url=config.api_base_url,
        )

    def source_for_pipeline(self, config: SentrySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return sentry_source(
            auth_token=config.auth_token,
            organization_slug=config.organization_slug,
            api_base_url=config.api_base_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

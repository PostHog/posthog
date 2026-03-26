from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    Option,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
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
from posthog.temporal.data_imports.sources.sentry.settings import (
    ALLOWED_SENTRY_API_BASE_URLS,
    DEFAULT_SENTRY_API_BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)

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
            caption="""Enter a Sentry auth token and your organization slug to sync Sentry organization, project, issue, and monitor datasets.

Create a token in Sentry and make sure it includes the scopes below if you want to sync all datasets:
- `alerts:read`
- `event:read`
- `member:read`
- `org:read`
- `project:read`
- `team:read`
""",
            docsUrl="https://posthog.com/docs/cdp/sources/sentry",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="324587...",
                    ),
                    SourceFieldInputConfig(
                        name="organization_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-org",
                    ),
                    SourceFieldSelectConfig(
                        name="api_base_url",
                        label="API base URL",
                        required=False,
                        defaultValue=DEFAULT_SENTRY_API_BASE_URL,
                        options=[
                            Option(label=DEFAULT_SENTRY_API_BASE_URL, value=DEFAULT_SENTRY_API_BASE_URL),
                            Option(label="https://us.sentry.io", value="https://us.sentry.io"),
                            Option(label="https://de.sentry.io", value="https://de.sentry.io"),
                        ],
                    ),
                ],
            ),
            betaSource=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Sentry auth token. Please update your token and reconnect.",
            "403 Client Error": "Sentry token is missing required scopes. Please make sure it includes all scopes required for your schemas.",
            "404 Client Error": "Sentry organization not found. Verify your organization slug.",
        }

    def get_schemas(
        self, config: SentrySourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = []
        for endpoint in ENDPOINTS:
            if names and endpoint not in names:
                continue
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            supports_incremental = bool(incremental_fields)
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=incremental_fields,
                )
            )
        return schemas

    def validate_credentials(
        self, config: SentrySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        api_base_url = config.api_base_url or DEFAULT_SENTRY_API_BASE_URL

        if api_base_url not in ALLOWED_SENTRY_API_BASE_URLS:
            return (
                False,
                "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
            )

        return validate_sentry_credentials(
            auth_token=config.auth_token,
            organization_slug=config.organization_slug,
            api_base_url=api_base_url,
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

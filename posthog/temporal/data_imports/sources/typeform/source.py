from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import TypeformSourceConfig
from posthog.temporal.data_imports.sources.typeform.settings import (
    ALLOWED_TYPEFORM_API_BASE_URLS,
    DEFAULT_TYPEFORM_API_BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.typeform.typeform import (
    typeform_source,
    validate_credentials as validate_typeform_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TypeformSource(SimpleSource[TypeformSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TYPEFORM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TYPEFORM,
            label="Typeform",
            iconPath="/static/services/typeform.png",
            caption="""Enter a Typeform personal access token to sync forms and responses.

Supported endpoints:
- `forms`
- `responses`

Required scopes:
- `forms:read`
- `responses:read`

You can generate a personal access token in your [Typeform account settings](https://admin.typeform.com/user/tokens).
""",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="tfp_...",
                    ),
                    SourceFieldSelectConfig(
                        name="api_base_url",
                        label="API base URL",
                        required=False,
                        defaultValue=DEFAULT_TYPEFORM_API_BASE_URL,
                        options=[
                            SourceFieldSelectConfigOption(
                                label=DEFAULT_TYPEFORM_API_BASE_URL, value=DEFAULT_TYPEFORM_API_BASE_URL
                            ),
                            SourceFieldSelectConfigOption(
                                label="https://api.eu.typeform.com", value="https://api.eu.typeform.com"
                            ),
                            SourceFieldSelectConfigOption(
                                label="https://api.typeform.eu", value="https://api.typeform.eu"
                            ),
                        ],
                    ),
                ],
            ),
            releaseStatus="beta",
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Typeform personal access token. Please update your token and reconnect.",
            "403 Client Error": "Typeform token is missing required scopes. Please update the token permissions.",
        }

    def get_schemas(
        self, config: TypeformSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
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
        self, config: TypeformSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        api_base_url = config.api_base_url or DEFAULT_TYPEFORM_API_BASE_URL
        if api_base_url not in ALLOWED_TYPEFORM_API_BASE_URLS:
            return (
                False,
                "API base URL must be one of https://api.typeform.com, https://api.eu.typeform.com, or https://api.typeform.eu.",
            )

        return validate_typeform_credentials(
            auth_token=config.auth_token,
            api_base_url=api_base_url,
            schema_name=schema_name,
        )

    def source_for_pipeline(self, config: TypeformSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return typeform_source(
            auth_token=config.auth_token,
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

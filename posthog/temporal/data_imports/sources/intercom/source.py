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
from posthog.temporal.data_imports.sources.generated_configs import IntercomSourceConfig
from posthog.temporal.data_imports.sources.intercom.intercom import (
    intercom_source,
    validate_credentials as validate_intercom_credentials,
)
from posthog.temporal.data_imports.sources.intercom.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IntercomSource(SimpleSource[IntercomSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTERCOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INTERCOM,
            label="Intercom",
            betaSource=True,
            caption="""Enter your Intercom API key to automatically pull your Intercom data into the PostHog Data warehouse.

You can find your API key in your [Intercom Developer Hub](https://developers.intercom.com/) under **Authentication**.
""",
            iconPath="/static/services/intercom.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your_intercom_api_key",
                    ),
                ],
            ),
        )

    def get_schemas(
        self, config: IntercomSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: IntercomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_intercom_credentials(config.api_key)

    def source_for_pipeline(self, config: IntercomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return intercom_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.intercom.io": "Your Intercom API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.intercom.io": "Your Intercom API key does not have the required permissions. Please check the API key scopes and try again.",
        }

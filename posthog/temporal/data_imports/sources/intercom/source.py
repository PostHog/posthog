from typing import cast

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
from posthog.temporal.data_imports.sources.intercom.settings import (
    ENDPOINTS as INTERCOM_ENDPOINTS,
    INCREMENTAL_FIELDS as INTERCOM_INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
)
from posthog.temporal.data_imports.sources.intercom.intercom import (
    intercom_source,
    validate_credentials as validate_intercom_credentials,
)

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
            caption="""Connect your Intercom workspace to automatically sync contacts, conversations, companies, and more into PostHog.

You'll need to create an access token in your Intercom workspace. Follow these steps:

1. Navigate to your [Intercom Developer Hub](https://app.intercom.com/a/apps/_/developer-hub)
2. Create a new app or select an existing one
3. Go to the **Configure > Authentication** section
4. Copy your **Access Token**

The token should start with `dG9r...`
""",
            iconPath="/static/services/intercom.png",
            docsUrl="https://posthog.com/docs/cdp/sources/intercom",
            feature_flag="dwh_intercom",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="dG9r...",
                    ),
                ],
            ),
        )

    def validate_credentials(self, config: IntercomSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_intercom_credentials(config.access_token):
                return True, None
            else:
                return False, "Invalid Intercom credentials"
        except Exception as e:
            return False, str(e)

    def get_schemas(self, config: IntercomSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INTERCOM_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INTERCOM_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INTERCOM_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in INTERCOM_ENDPOINTS
        ]

    def source_for_pipeline(self, config: IntercomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        source_response = intercom_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
        )

        partition_key = PARTITION_FIELDS.get(inputs.schema_name, None)

        if partition_key:
            # Determine partition mode based on the field type
            if partition_key in ["created_at", "updated_at"]:
                source_response.partition_mode = "datetime"
                source_response.partition_format = "month"
            else:
                # For id-based partitioning, use numerical mode
                source_response.partition_mode = "md5"
                source_response.partition_count = 100

            source_response.partition_keys = [partition_key]

        return source_response

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
from posthog.temporal.data_imports.sources.generated_configs import PostmarkSourceConfig
from posthog.temporal.data_imports.sources.postmark.postmark import (
    postmark_source,
    validate_credentials as validate_postmark_credentials,
)
from posthog.temporal.data_imports.sources.postmark.settings import (
    ENDPOINTS as POSTMARK_ENDPOINTS,
    INCREMENTAL_FIELDS as POSTMARK_INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PostmarkSource(SimpleSource[PostmarkSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTMARK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POSTMARK,
            caption="""Enter your Postmark API credentials to automatically pull your Postmark email data into the PostHog Data warehouse.

You can find your Server API Token in your [Postmark Server settings](https://account.postmarkapp.com/servers). Make sure the token has read access to the data you want to import.

The following data will be available to import:
- **Bounces**: Email bounce information
- **Messages**: Outbound email messages
- **Message streams**: Message stream configurations
- **Servers**: Server configurations
- **Domains**: Domain settings and verification status
- **Delivery stats**: Email delivery statistics
""",
            iconPath="/static/services/postmark.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/postmark",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="server_token",
                        label="Server API Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                    ),
                ],
            ),
            feature_flag="dwh_postmark",
        )

    def get_schemas(self, config: PostmarkSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=POSTMARK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=POSTMARK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=POSTMARK_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in POSTMARK_ENDPOINTS
        ]

    def validate_credentials(self, config: PostmarkSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if validate_postmark_credentials(config.server_token):
            return True, None

        return False, "Invalid Postmark credentials. Please check your Server API Token."

    def source_for_pipeline(self, config: PostmarkSourceConfig, inputs: SourceInputs) -> SourceResponse:
        items = postmark_source(
            server_token=config.server_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
        )

        # Configure partitioning for incremental endpoints
        partition_key = PARTITION_FIELDS.get(inputs.schema_name, None)

        response = SourceResponse(
            name=inputs.schema_name,
            items=lambda: items,
            primary_keys=["ID"] if inputs.schema_name in ["bounces", "message_streams", "servers", "domains"]
                         else ["MessageID"] if inputs.schema_name == "messages"
                         else ["Name"],
        )

        # Set up partitioning for incremental endpoints
        if partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "month"
            response.partition_keys = [partition_key]

        return response

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
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.generated_configs import MailchimpSourceConfig
from posthog.temporal.data_imports.sources.mailchimp.mailchimp import (
    mailchimp_source,
    validate_credentials as validate_mailchimp_credentials,
)
from posthog.temporal.data_imports.sources.mailchimp.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailchimpSource(SimpleSource[MailchimpSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILCHIMP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILCHIMP,
            label="Mailchimp",
            iconPath="/static/services/mailchimp.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailchimp",
            caption="""Enter your Mailchimp API key to automatically pull your Mailchimp data into the PostHog Data warehouse.

You can find your API key by logging into your Mailchimp account and navigating to **Account** > **Extras** > **API keys**. If you don't have an API key yet, you can create one by clicking **Create A Key**.

Your API key will include a server prefix (e.g., `abc123-us19`) which identifies your Mailchimp data center. This is automatically detected from your API key.
            """,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="abc123-us19",
                    ),
                ],
            ),
            featureFlag="dwh_mailchimp",
        )

    def get_schemas(self, config: MailchimpSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def validate_credentials(self, config: MailchimpSourceConfig, team_id: int) -> tuple[bool, str | None]:
        is_valid, result = validate_mailchimp_credentials(config.api_key)
        if is_valid:
            return True, None
        return False, result

    def source_for_pipeline(self, config: MailchimpSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            mailchimp_source(
                api_key=config.api_key,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )

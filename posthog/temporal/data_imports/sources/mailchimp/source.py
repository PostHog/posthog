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
            betaSource=True,
            caption="""Enter your Mailchimp API key to automatically pull your Mailchimp data into the PostHog Data warehouse.

You can create an API key in your [Mailchimp account settings](https://us1.admin.mailchimp.com/account/api/).

The API key format is: `key-dc` (e.g., `abc123def456-us6`), where `dc` is the data center for your account.
""",
            iconPath="/static/services/mailchimp.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailchimp",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="abc123def456-us6",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Mailchimp API key. Please check your API key and try again.",
            "403 Client Error": "Access forbidden. Your API key may lack required permissions.",
            "Invalid Mailchimp API key format": "Invalid API key format. Expected format: key-dc (e.g., abc123-us6)",
        }

    def get_schemas(self, config: MailchimpSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
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
        self, config: MailchimpSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_mailchimp_credentials(config.api_key)

    def source_for_pipeline(self, config: MailchimpSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return mailchimp_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

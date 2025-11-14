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
from posthog.temporal.data_imports.sources.mailchimp.settings import (
    ENDPOINTS as MAILCHIMP_ENDPOINTS,
    INCREMENTAL_FIELDS as MAILCHIMP_INCREMENTAL_FIELDS,
)

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
            caption="""Connect your Mailchimp account to automatically import your email marketing data into PostHog.

You'll need a Mailchimp API key which you can create [in your Mailchimp account](https://admin.mailchimp.com/account/api/).

Your API key should be in the format: `<key>-<datacenter>` (e.g., `abc123-us19`). The data center is automatically extracted from your API key.""",
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
                        placeholder="abc123-us19",
                    ),
                ],
            ),
            feature_flag="dwh_mailchimp",
        )

    def validate_credentials(self, config: MailchimpSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_mailchimp_credentials(config.api_key):
                return True, None
            else:
                return False, "Invalid Mailchimp API key"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Error validating credentials: {str(e)}"

    def get_schemas(self, config: MailchimpSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=MAILCHIMP_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=MAILCHIMP_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=MAILCHIMP_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in MAILCHIMP_ENDPOINTS
        ]

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
                logger=inputs.logger,
            )
        )

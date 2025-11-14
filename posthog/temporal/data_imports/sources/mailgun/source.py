from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import MailgunSourceConfig
from posthog.temporal.data_imports.sources.mailgun.mailgun import (
    mailgun_source,
    validate_credentials as validate_mailgun_credentials,
)
from posthog.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS as MAILGUN_ENDPOINTS,
    INCREMENTAL_FIELDS as MAILGUN_INCREMENTAL_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailgunSource(SimpleSource[MailgunSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILGUN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILGUN,
            caption="""Enter your Mailgun credentials to automatically pull your Mailgun data into the PostHog Data warehouse.

You can find your API key in your Mailgun dashboard under Settings > API Keys. Select your private API key.

Your domain is the sending domain you have configured in Mailgun (e.g., mg.example.com).

Select the region where your Mailgun account is hosted (US or EU).
""",
            iconPath="/static/services/mailgun.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/mailgun",
            featureFlag="dwh_mailgun",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="key-...",
                    ),
                    SourceFieldInputConfig(
                        name="domain",
                        label="Domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mg.example.com",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="US",
                        options=[
                            {"label": "US", "value": "US"},
                            {"label": "EU", "value": "EU"},
                        ],
                    ),
                ],
            ),
        )

    def get_schemas(self, config: MailgunSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=MAILGUN_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=MAILGUN_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in MAILGUN_ENDPOINTS
        ]

    def validate_credentials(self, config: MailgunSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_mailgun_credentials(config.api_key, config.domain, config.region):
                return True, None
            else:
                return False, "Invalid Mailgun credentials or domain not found"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: MailgunSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return mailgun_source(
            api_key=config.api_key,
            domain=config.domain,
            region=config.region,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
        )

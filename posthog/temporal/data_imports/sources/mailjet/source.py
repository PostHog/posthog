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
from posthog.temporal.data_imports.sources.generated_configs import MailjetSourceConfig
from posthog.temporal.data_imports.sources.mailjet.mailjet import (
    mailjet_source,
    validate_credentials as validate_mailjet_credentials,
)
from posthog.temporal.data_imports.sources.mailjet.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailJetSource(SimpleSource[MailjetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILJET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILJET,
            label="Mailjet",
            iconPath="/static/services/mailjet.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailjet",
            caption="""Connect your Mailjet account to automatically sync your email data to PostHog.

You can find your API key and Secret key in your [Mailjet account settings](https://app.mailjet.com/account/api_keys).

**Note:** Make sure you have the appropriate permissions to access the Mailjet API.
""",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your_api_key",
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your_secret_key",
                    ),
                ],
            ),
            featureFlag="dwh_mailjet",
        )

    def get_schemas(self, config: MailjetSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None
                and len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None
                and len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: MailjetSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mailjet_credentials(config.api_key, config.api_secret):
            return True, None

        return False, "Invalid Mailjet credentials"

    def source_for_pipeline(self, config: MailjetSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return mailjet_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

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
from posthog.temporal.data_imports.sources.generated_configs import TwilioSourceConfig
from posthog.temporal.data_imports.sources.twilio.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.twilio.twilio import (
    twilio_source,
    validate_credentials as validate_twilio_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwilioSource(SimpleSource[TwilioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWILIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWILIO,
            caption="""Enter your Twilio credentials to automatically pull your Twilio data into the PostHog Data warehouse.

You can find your Account SID and Auth Token in the [Twilio Console](https://console.twilio.com/).

Navigate to **Account > API keys & tokens** to find your Account SID and create or view your Auth Token.

**Authentication**: Twilio uses HTTP Basic authentication with your Account SID as the username and Auth Token as the password.
""",
            iconPath="/static/services/twilio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/twilio",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_sid",
                        label="Account SID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AC...",
                    ),
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your_auth_token",
                    ),
                ],
            ),
            featureFlag="dwh_twilio",
        )

    def validate_credentials(self, config: TwilioSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_twilio_credentials(config.account_sid, config.auth_token):
                return True, None
            return False, "Invalid Twilio credentials"
        except Exception as e:
            return False, str(e)

    def get_schemas(self, config: TwilioSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: TwilioSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return twilio_source(
            account_sid=config.account_sid,
            auth_token=config.auth_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.appsflyer.appsflyer import (
    appsflyer_source,
    validate_credentials as validate_appsflyer_credentials,
)
from posthog.temporal.data_imports.sources.appsflyer.settings import (
    ENDPOINTS as APPSFLYER_ENDPOINTS,
    INCREMENTAL_FIELDS as APPSFLYER_INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
)
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import AppsFlyerSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppsFlyerSource(SimpleSource[AppsFlyerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPSFLYER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPS_FLYER,
            caption="""Enter your AppsFlyer credentials to automatically pull your AppsFlyer data into the PostHog Data warehouse.

You can find your API token in the [AppsFlyer dashboard](https://hq1.appsflyer.com/auth/login) under **Configuration** → **APIs** → **API V2.0 tokens**.

Your app ID is the unique identifier for your app in AppsFlyer (e.g., `com.example.myapp` for Android or `id123456789` for iOS).

Currently, the following reports are supported:

**Raw Data Reports:**
- Install events (non-organic and organic)
- In-app events
- Uninstall events
- Reinstall events
- Retargeting conversion and in-app events

**Aggregate Reports:**
- Partners report (by media source and campaign)
- Partners by date report
- Geo by date report
- Daily report
""",
            iconPath="/static/services/appsflyer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appsflyer",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Bearer token from AppsFlyer dashboard",
                    ),
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="com.example.myapp",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD (e.g., 2025-01-01)",
                    ),
                ],
            ),
            feature_flag="dwh_appsflyer",
        )

    def get_schemas(self, config: AppsFlyerSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=APPSFLYER_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=APPSFLYER_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=APPSFLYER_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in APPSFLYER_ENDPOINTS
        ]

    def validate_credentials(self, config: AppsFlyerSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_appsflyer_credentials(config.api_token, config.app_id):
                return True, None
            else:
                return False, "Invalid AppsFlyer credentials or app ID"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: AppsFlyerSourceConfig, inputs: SourceInputs) -> SourceResponse:
        appsflyer_source_response = appsflyer_source(
            api_token=config.api_token,
            app_id=config.app_id,
            endpoint=inputs.schema_name,
            start_date=config.start_date,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

        partition_key = PARTITION_FIELDS.get(inputs.schema_name, None)

        # All partition keys are datetime or date fields
        if partition_key:
            appsflyer_source_response.partition_count = 1
            appsflyer_source_response.partition_size = 1
            appsflyer_source_response.partition_mode = "datetime"
            appsflyer_source_response.partition_format = "month"
            appsflyer_source_response.partition_keys = [partition_key]

        return appsflyer_source_response

from typing import Optional, cast

import requests

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.appsflyer.appsflyer import (
    AppsFlyerRetryableError,
    appsflyer_source,
    validate_credentials as validate_appsflyer_credentials,
)
from posthog.temporal.data_imports.sources.appsflyer.settings import ENDPOINTS, INCREMENTAL_FIELDS
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
    def connection_host_fields(self) -> list[str]:
        # app_id selects which AppsFlyer app the stored token is used against; changing it must
        # require re-entering the secret so a preserved token can't be retargeted at another app.
        return ["app_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://hq1.appsflyer.com": "AppsFlyer authentication failed. Please check your API token (V2).",
            "403 Client Error: Forbidden for url: https://hq1.appsflyer.com": "AppsFlyer denied access. Please check that your account's subscription includes the aggregate Pull API and the app id is correct.",
            "404 Client Error: Not Found for url: https://hq1.appsflyer.com": "AppsFlyer app not found. Please check the app id.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPS_FLYER,
            label="AppsFlyer",
            caption="""Enter your AppsFlyer credentials to pull aggregate performance reports into the PostHog Data warehouse.

You can find your API token (V2) in AppsFlyer under your account menu > Security center > AppsFlyer API tokens. The app id is your app's identifier as shown in the dashboard (e.g. `id123456789` for iOS or the package name for Android) — add one source per app.""",
            iconPath="/static/services/appsflyer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appsflyer",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="id123456789",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token (V2)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AppsFlyerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
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
        self, config: AppsFlyerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_appsflyer_credentials(config.api_token, config.app_id):
                return True, None
        except (AppsFlyerRetryableError, requests.RequestException):
            # A rate-limit, 5xx, or network blip isn't a bad credential — don't mislabel it.
            return (
                False,
                "Could not reach AppsFlyer to validate credentials. This may be a temporary rate-limit or network issue — please try again.",
            )

        return False, "Invalid AppsFlyer API token or app id"

    def source_for_pipeline(self, config: AppsFlyerSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return appsflyer_source(
            api_token=config.api_token,
            app_id=config.app_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

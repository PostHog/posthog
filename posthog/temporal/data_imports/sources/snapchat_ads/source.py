from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SnapchatAdsSourceConfig
from posthog.temporal.data_imports.sources.snapchat_ads.settings import SNAPCHAT_ADS_CONFIG
from posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads import snapchat_ads_source

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SnapchatAdsSource(SimpleSource[SnapchatAdsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNAPCHATADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SNAPCHAT_ADS,
            label="Snapchat Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from Snapchat Ads. Ensure you have granted PostHog access to your Snapchat Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/snapchat-ads).",
            betaSource=True,
            featureFlag="snapchat-ads-source",
            iconPath="/static/services/snapchat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/snapchat-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="ad_account_id",
                        label="Snapchat Ads Ad Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Snapchat Ads ad account ID",
                    ),
                    SourceFieldOauthConfig(
                        name="snapchat_integration_id",
                        label="Snapchat Ads account",
                        required=True,
                        kind="snapchat",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: SnapchatAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.ad_account_id or not config.snapchat_integration_id:
            return False, "Ad Account ID and Snapchat Ads integration are required"

        try:
            self.get_oauth_integration(config.snapchat_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Snapchat Ads credentials: {str(e)}"

    def get_schemas(
        self, config: SnapchatAdsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=str(endpoint_config.resource["name"]),
                supports_incremental=endpoint_config.incremental_fields is not None,
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields or [],
            )
            for endpoint_config in SNAPCHAT_ADS_CONFIG.values()
        ]

    def source_for_pipeline(self, config: SnapchatAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.snapchat_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Snapchat Ads access token not found for job {inputs.job_id}")

        return snapchat_ads_source(
            ad_account_id=config.ad_account_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            access_token=integration.access_token,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

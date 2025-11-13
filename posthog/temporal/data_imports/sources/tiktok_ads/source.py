from typing import cast

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
from posthog.temporal.data_imports.sources.generated_configs import TikTokAdsSourceConfig
from posthog.temporal.data_imports.sources.tiktok_ads.settings import TIKTOK_ADS_CONFIG
from posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads import tiktok_ads_source

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TikTokAdsSource(SimpleSource[TikTokAdsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TIKTOKADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TIK_TOK_ADS,
            label="TikTok Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from TikTok Ads. Ensure you have granted PostHog access to your TikTok Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/tiktok-ads).",
            betaSource=True,
            iconPath="/static/services/tiktok.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tiktok-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="advertiser_id",
                        label="TikTok Ads Advertiser ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your TikTok Ads advertiser ID",
                    ),
                    SourceFieldOauthConfig(
                        name="tiktok_integration_id",
                        label="TikTok Ads account",
                        required=True,
                        kind="tiktok-ads",
                    ),
                ],
            ),
        )

    def validate_credentials(self, config: TikTokAdsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.advertiser_id or not config.tiktok_integration_id:
            return False, "Advertiser ID and TikTok Ads integration are required"

        try:
            self.get_oauth_integration(config.tiktok_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate TikTok Ads credentials: {str(e)}"

    def get_schemas(self, config: TikTokAdsSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=str(endpoint_config.resource["name"]),
                supports_incremental=endpoint_config.incremental_fields is not None,
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields or [],
            )
            for endpoint_config in TIKTOK_ADS_CONFIG.values()
        ]

    def source_for_pipeline(self, config: TikTokAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.tiktok_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"TikTok Ads access token not found for job {inputs.job_id}")

        return tiktok_ads_source(
            advertiser_id=config.advertiser_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            access_token=integration.access_token,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

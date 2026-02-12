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
from posthog.temporal.data_imports.sources.generated_configs import PinterestAdsSourceConfig
from posthog.temporal.data_imports.sources.pinterest_ads.pinterest_ads import pinterest_ads_source
from posthog.temporal.data_imports.sources.pinterest_ads.settings import PINTEREST_ADS_CONFIG
from posthog.temporal.data_imports.sources.pinterest_ads.utils import validate_ad_account

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PinterestAdsSource(SimpleSource[PinterestAdsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINTERESTADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PINTEREST_ADS,
            label="Pinterest Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from Pinterest Ads. Ensure you have granted PostHog access to your Pinterest Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/pinterest-ads).",
            betaSource=True,
            featureFlag="pinterest-ads-source",
            iconPath="/static/services/pinterest.com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pinterest-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="ad_account_id",
                        label="Pinterest Ads Ad Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Pinterest Ads ad account ID",
                    ),
                    SourceFieldOauthConfig(
                        name="pinterest_ads_integration_id",
                        label="Pinterest Ads account",
                        required=True,
                        kind="pinterest-ads",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: PinterestAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.ad_account_id or not config.pinterest_ads_integration_id:
            return False, "Ad Account ID and Pinterest Ads integration are required"

        try:
            integration = self.get_oauth_integration(config.pinterest_ads_integration_id, team_id)

            if not integration.access_token:
                return False, "Pinterest Ads access token not found"

            is_valid, error_message = validate_ad_account(integration.access_token, config.ad_account_id)
            if not is_valid:
                return False, error_message

            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Pinterest Ads credentials: {str(e)}"

    def get_schemas(
        self, config: PinterestAdsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.incremental_fields is not None,
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields or [],
            )
            for endpoint_config in PINTEREST_ADS_CONFIG.values()
        ]

    def source_for_pipeline(self, config: PinterestAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.pinterest_ads_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Pinterest Ads access token not found for job {inputs.job_id}")

        return pinterest_ads_source(
            ad_account_id=config.ad_account_id,
            endpoint=inputs.schema_name,
            access_token=integration.access_token,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

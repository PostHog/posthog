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
from posthog.temporal.data_imports.sources.generated_configs import BingAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

from .bing_ads import bing_ads_source, get_incremental_fields, get_schemas


@SourceRegistry.register
class BingAdsSource(SimpleSource[BingAdsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BINGADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BING_ADS,
            label="Bing Ads",
            caption="Ensure you have granted PostHog access to your Bing Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/bing-ads).",
            betaSource=True,
            featureFlag="bing-ads-source",
            iconPath="/static/services/bing-ads.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/bing-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldOauthConfig(
                        name="bing_ads_integration_id",
                        label="Bing Ads account",
                        required=True,
                        kind="bing-ads",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: BingAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.account_id or not config.bing_ads_integration_id:
            return False, "Account ID and Bing Ads integration are required"

        try:
            self.get_oauth_integration(config.bing_ads_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Bing Ads credentials: {str(e)}"

    def get_schemas(self, config: BingAdsSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        bing_ads_schemas = get_schemas()
        ads_incremental_fields = get_incremental_fields()

        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=ads_incremental_fields.get(endpoint, None) is not None,
                supports_append=ads_incremental_fields.get(endpoint, None) is not None,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in ads_incremental_fields.get(endpoint, [])
                ],
            )
            for endpoint in bing_ads_schemas.keys()
        ]

    def source_for_pipeline(self, config: BingAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.bing_ads_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Bing Ads access token not found for job {inputs.job_id}")
        if not integration.refresh_token:
            raise ValueError(f"Bing Ads refresh token not found for job {inputs.job_id}")

        return bing_ads_source(
            account_id=config.account_id,
            resource_name=inputs.schema_name,
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SuggestedTable,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import (
    MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
    FieldType,
    ResumableSource,
)
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import BingAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

from .bing_ads import bing_ads_source, get_incremental_fields, get_schemas
from .utils import BingAdsResumeConfig


@SourceRegistry.register
class BingAdsSource(ResumableSource[BingAdsSourceConfig, BingAdsResumeConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BINGADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BING_ADS,
            label="Bing Ads",
            caption="Ensure you have granted PostHog access to your Bing Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/bing-ads).",
            releaseStatus="beta",
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
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="bing_ads_integration_id",
                        label="Bing Ads account",
                        required=True,
                        kind="bing-ads",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaigns",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_performance_report",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def validate_credentials(
        self, config: BingAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.account_id or not config.bing_ads_integration_id:
            return False, "Account ID and Bing Ads integration are required"

        if not config.account_id.isdigit():
            return (
                False,
                f"Invalid Account ID '{config.account_id}'. Bing Ads Account IDs are numeric. You can find your Account ID in the Bing Ads dashboard under Settings > Account.",
            )

        try:
            self.get_oauth_integration(config.bing_ads_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Bing Ads credentials: {str(e)}"

    def get_schemas(
        self, config: BingAdsSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        bing_ads_schemas = get_schemas()
        ads_incremental_fields = get_incremental_fields()

        schemas = [
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

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BingAdsResumeConfig]:
        return ResumableSourceManager[BingAdsResumeConfig](inputs, BingAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: BingAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[BingAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
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
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

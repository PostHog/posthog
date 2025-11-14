from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import PinterestAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

from .pinterest_ads import (
    get_incremental_fields as get_pinterest_ads_incremental_fields,
    get_schemas as get_pinterest_ads_schemas,
    pinterest_ads_source,
)


@SourceRegistry.register
class PinterestAdsSource(SimpleSource[PinterestAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINTERESTADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PINTEREST_ADS,
            label="Pinterest Ads",
            caption="Ensure you have granted PostHog access to your Pinterest Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/pinterest-ads).",
            betaSource=True,
            iconPath="/static/services/pinterest.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pinterest-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="ad_account_id",
                        label="Ad Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="549755885175",
                    ),
                    SourceFieldOauthConfig(
                        name="pinterest_ads_integration_id",
                        label="Pinterest Ads account",
                        required=True,
                        kind="pinterest-ads",
                    ),
                ],
            ),
            featureFlag="dwh_pinterest_ads",
        )

    def validate_credentials(self, config: PinterestAdsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.ad_account_id or not config.pinterest_ads_integration_id:
            return False, "Ad Account ID and Pinterest Ads integration are required"

        try:
            Integration.objects.get(id=config.pinterest_ads_integration_id, team_id=team_id)
            return True, None
        except Integration.DoesNotExist:
            return False, "Pinterest Ads integration not found. Please re-authenticate."
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Pinterest Ads credentials: {str(e)}"

    def get_schemas(
        self, config: PinterestAdsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        pinterest_ads_schemas = get_pinterest_ads_schemas()
        ads_incremental_fields = get_pinterest_ads_incremental_fields()

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
            for endpoint in pinterest_ads_schemas.keys()
        ]

    def source_for_pipeline(self, config: PinterestAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return pinterest_ads_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

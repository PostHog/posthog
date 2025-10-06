from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import MetaAdsSourceConfig
from posthog.temporal.data_imports.sources.meta_ads.meta_ads import meta_ads_source
from posthog.temporal.data_imports.sources.meta_ads.schemas import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class MetaAdsSource(BaseSource[MetaAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METAADS

    def get_schemas(self, config: MetaAdsSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: MetaAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return meta_ads_source(
            resource_name=inputs.schema_name,
            config=config,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.META_ADS,
            label="Meta Ads",
            caption="Ensure you have granted PostHog access to your Meta Ads account, learn how to do this in the [documentation](https://posthog.com/docs/cdp/sources/meta-ads).",
            iconPath="/static/services/meta-ads.png",
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
                        name="meta_ads_integration_id",
                        label="Meta Ads account",
                        required=True,
                        kind="meta-ads",
                    ),
                ],
            ),
            betaSource=True,
            featureFlag="meta-ads-dwh",
        )

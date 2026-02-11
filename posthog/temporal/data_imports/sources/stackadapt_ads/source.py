from typing import Optional, cast

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
from posthog.temporal.data_imports.sources.generated_configs import StackAdaptAdsSourceConfig
from posthog.temporal.data_imports.sources.stackadapt_ads.settings import ENDPOINT_CONFIGS
from posthog.temporal.data_imports.sources.stackadapt_ads.stackadapt_ads import (
    stackadapt_ads_source,
    validate_credentials as validate_stackadapt_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StackAdaptAdsSource(SimpleSource[StackAdaptAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STACKADAPTADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STACK_ADAPT_ADS,
            label="StackAdapt Ads",
            caption="Collect campaign data and advertising metrics from StackAdapt. Learn more in [the documentation](https://posthog.com/docs/cdp/sources/stackadapt-ads).",
            betaSource=True,
            unreleasedSource=True,
            featureFlag="stackadapt-ads-source",
            iconPath="/static/services/stackadapt.com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stackadapt-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="StackAdapt GraphQL API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your StackAdapt GraphQL API token",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: StackAdaptAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            validate_stackadapt_credentials(config.api_token)
            return True, None
        except Exception as e:
            return False, f"Failed to validate StackAdapt credentials: {str(e)}"

    def get_schemas(
        self, config: StackAdaptAdsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint_name,
                supports_incremental=endpoint_config.fields is not None and len(endpoint_config.fields) > 0,
                supports_append=False,
                incremental_fields=endpoint_config.fields or [],
            )
            for endpoint_name, endpoint_config in ENDPOINT_CONFIGS.items()
        ]

    def source_for_pipeline(self, config: StackAdaptAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return stackadapt_ads_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

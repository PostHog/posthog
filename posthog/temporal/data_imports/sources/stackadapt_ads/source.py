from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import StackAdaptAdsSourceConfig

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
            iconPath="/static/services/stackadapt.com.png",
            unreleasedSource=True,
            betaSource=True,
            featureFlag="stackadapt-ads-source",
            fields=cast(list[FieldType], []),
        )

    def validate_credentials(
        self, config: StackAdaptAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        raise NotImplementedError("StackAdapt validation not yet implemented")

    def get_schemas(
        self, config: StackAdaptAdsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        raise NotImplementedError("StackAdapt schemas not yet implemented")

    def source_for_pipeline(self, config: StackAdaptAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError("StackAdapt pipeline not yet implemented")

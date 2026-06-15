from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import LightspeedRetailSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LightspeedRetailSource(SimpleSource[LightspeedRetailSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIGHTSPEEDRETAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LIGHTSPEED_RETAIL,
            label="Lightspeed Retail",
            iconPath="/static/services/lightspeed_retail.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

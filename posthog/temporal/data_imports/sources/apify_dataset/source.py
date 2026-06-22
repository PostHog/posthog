from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ApifyDatasetSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ApifyDatasetSource(SimpleSource[ApifyDatasetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APIFYDATASET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APIFY_DATASET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Apify Dataset",
            iconPath="/static/services/apify_dataset.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

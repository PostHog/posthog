from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import OneHundredMsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OneHundredMsSource(SimpleSource[OneHundredMsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONEHUNDREDMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ONE_HUNDRED_MS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="100ms",
            iconPath="/static/services/onehundredms.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

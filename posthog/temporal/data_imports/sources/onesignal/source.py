from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import OneSignalSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OneSignalSource(SimpleSource[OneSignalSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONESIGNAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ONE_SIGNAL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="OneSignal",
            iconPath="/static/services/onesignal.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

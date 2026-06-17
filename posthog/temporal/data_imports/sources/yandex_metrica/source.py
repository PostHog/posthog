from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import YandexMetricaSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YandexMetricaSource(SimpleSource[YandexMetricaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YANDEXMETRICA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.YANDEX_METRICA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Yandex Metrica",
            iconPath="/static/services/yandex_metrica.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

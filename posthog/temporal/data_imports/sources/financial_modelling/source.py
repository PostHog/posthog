from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import FinancialModellingSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FinancialModellingSource(SimpleSource[FinancialModellingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINANCIALMODELLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FINANCIAL_MODELLING,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Financial Modelling",
            iconPath="/static/services/financial_modelling.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

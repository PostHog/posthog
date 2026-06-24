from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import BraintrustSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BraintrustSource(SimpleSource[BraintrustSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRAINTRUST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BRAINTRUST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["llm", "evals", "ai"],
            label="Braintrust",
            iconPath="/static/services/braintrust.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

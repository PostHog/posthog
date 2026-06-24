from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import LinkrunnerSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LinkrunnerSource(SimpleSource[LinkrunnerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINKRUNNER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINKRUNNER,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Linkrunner",
            iconPath="/static/services/linkrunner.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ConstantContactSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConstantContactSource(SimpleSource[ConstantContactSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONSTANTCONTACT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONSTANT_CONTACT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Constant Contact",
            iconPath="/static/services/constant_contact.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

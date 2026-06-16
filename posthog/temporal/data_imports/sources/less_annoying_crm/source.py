from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import LessAnnoyingCRMSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LessAnnoyingCRMSource(SimpleSource[LessAnnoyingCRMSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LESSANNOYINGCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LESS_ANNOYING_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Less Annoying CRM",
            iconPath="/static/services/less_annoying_crm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

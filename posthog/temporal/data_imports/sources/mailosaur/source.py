from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import MailosaurSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailosaurSource(SimpleSource[MailosaurSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILOSAUR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILOSAUR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mailosaur",
            iconPath="/static/services/mailosaur.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

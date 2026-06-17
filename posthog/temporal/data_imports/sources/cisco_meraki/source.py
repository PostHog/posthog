from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import CiscoMerakiSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CiscoMerakiSource(SimpleSource[CiscoMerakiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CISCOMERAKI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CISCO_MERAKI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cisco Meraki",
            iconPath="/static/services/cisco_meraki.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

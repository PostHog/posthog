from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import IP2WhoisSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IP2WhoisSource(SimpleSource[IP2WhoisSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IP2WHOIS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.IP2_WHOIS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="IP2Whois",
            iconPath="/static/services/ip2whois.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

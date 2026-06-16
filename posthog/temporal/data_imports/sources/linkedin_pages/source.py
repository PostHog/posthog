from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import LinkedinPagesSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LinkedinPagesSource(SimpleSource[LinkedinPagesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINKEDINPAGES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINKEDIN_PAGES,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Linkedin Pages",
            iconPath="/static/services/linkedin_pages.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

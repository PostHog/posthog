from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import HuggingFaceSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HuggingFaceSource(SimpleSource[HuggingFaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUGGINGFACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HUGGING_FACE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hugging Face",
            iconPath="/static/services/hugging_face.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

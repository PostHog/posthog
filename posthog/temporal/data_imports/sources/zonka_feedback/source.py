from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ZonkaFeedbackSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZonkaFeedbackSource(SimpleSource[ZonkaFeedbackSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZONKAFEEDBACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZONKA_FEEDBACK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Zonka Feedback",
            iconPath="/static/services/zonka_feedback.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

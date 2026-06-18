from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AmazonS3SourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonS3Source(SimpleSource[AmazonS3SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONS3

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AMAZON_S3,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["s3"],
            label="Amazon S3",
            iconPath="/static/services/aws-s3.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

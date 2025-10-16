from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import TikTokAdsSourceConfig
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class TikTokAdsSource(BaseSource[TikTokAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TIKTOKADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TIK_TOK_ADS,
            label="TikTok Ads",
            caption="",
            iconPath="/static/services/tiktok.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )

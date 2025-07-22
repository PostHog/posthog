from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.meta_ads.schemas import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import MetaAdsSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class MetaAdsSource(BaseSource[MetaAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.METAADS

    def get_schemas(self, config: MetaAdsSourceConfig) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: MetaAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Meta Ads source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)

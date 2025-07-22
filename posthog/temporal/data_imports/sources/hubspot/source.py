from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.hubspot.settings import (
    ENDPOINTS as HUBSPOT_ENDPOINTS,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import HubspotSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class HubspotSource(BaseSource[HubspotSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.HUBSPOT

    def get_schemas(self, config: HubspotSourceConfig) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in HUBSPOT_ENDPOINTS
        ]

    def source_for_pipeline(self, config: HubspotSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Hubspot source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)

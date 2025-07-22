from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.google_ads import (
    get_incremental_fields as get_google_ads_incremental_fields,
    get_schemas as get_google_ads_schemas,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class GoogleAdsSource(BaseSource[GoogleAdsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.GOOGLEADS

    def get_schemas(self, config: GoogleAdsSourceConfig, team_id: int) -> list[SourceSchema]:
        # TODO: fix the below
        google_ads_schemas = get_google_ads_schemas(
            google_ads_config,
            team_id,
        )

        ads_incremental_fields = get_google_ads_incremental_fields()

        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=ads_incremental_fields.get(endpoint, None) is not None,
                supports_append=ads_incremental_fields.get(endpoint, None) is not None,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in ads_incremental_fields.get(endpoint, [])
                ],
            )
            for endpoint in google_ads_schemas.keys()
        ]

    def validate_credentials(self, config: GoogleAdsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        return True, None

    def source_for_pipeline(self, config: GoogleAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Google Ads source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)

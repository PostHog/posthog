from typing import cast
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldOauthConfig,
    Type4,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.google_ads import (
    GoogleAdsServiceAccountSourceConfig,
    get_incremental_fields as get_google_ads_incremental_fields,
    get_schemas as get_google_ads_schemas,
    google_ads_source,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class GoogleAdsSource(BaseSource[GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.GOOGLEADS

    # TODO: clean up google ads source to not have two auth config options
    def parse_config(self, job_inputs: dict) -> GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig:
        if "google_ads_integration_id" in job_inputs.keys():
            return self._config_class.from_dict(job_inputs)

        return GoogleAdsServiceAccountSourceConfig.from_dict(job_inputs)

    def get_schemas(
        self, config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig, team_id: int
    ) -> list[SourceSchema]:
        google_ads_schemas = get_google_ads_schemas(
            config,
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

    def source_for_pipeline(
        self, config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig, inputs: SourceInputs
    ) -> SourceResponse:
        return google_ads_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLE_ADS,
            label="Google Ads",
            caption="Ensure you have granted PostHog access to your Google Ads account, learn how to do this in [the docs](https://posthog.com/docs/cdp/sources/google-ads).",
            betaSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="customer_id", label="Customer ID", type=Type4.TEXT, required=True, placeholder=""
                    ),
                    SourceFieldOauthConfig(
                        name="google_ads_integration_id", label="Google Ads account", required=True, kind="google-ads"
                    ),
                ],
            ),
        )

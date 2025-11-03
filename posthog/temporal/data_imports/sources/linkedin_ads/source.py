from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

from .linkedin_ads import (
    get_incremental_fields as get_linkedin_ads_incremental_fields,
    get_schemas as get_linkedin_ads_schemas,
    linkedin_ads_source,
)


@SourceRegistry.register
class LinkedInAdsSource(BaseSource[LinkedinAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINKEDINADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINKEDIN_ADS,
            label="LinkedIn Ads",
            caption="Ensure you have granted PostHog access to your LinkedIn Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/linkedin-ads).",
            betaSource=True,
            iconPath="/static/services/linkedin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/linkedin-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldOauthConfig(
                        name="linkedin_ads_integration_id",
                        label="LinkedIn Ads account",
                        required=True,
                        kind="linkedin-ads",
                    ),
                ],
            ),
        )

    def validate_credentials(self, config: LinkedinAdsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.account_id or not config.linkedin_ads_integration_id:
            return False, "Account ID and LinkedIn Ads integration are required"

        try:
            Integration.objects.get(id=config.linkedin_ads_integration_id, team_id=team_id)
            return True, None
        except Integration.DoesNotExist:
            return False, "LinkedIn Ads integration not found. Please re-authenticate."
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate LinkedIn Ads credentials: {str(e)}"

    def get_schemas(
        self, config: LinkedinAdsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        linkedin_ads_schemas = get_linkedin_ads_schemas()
        ads_incremental_fields = get_linkedin_ads_incremental_fields()

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
            for endpoint in linkedin_ads_schemas.keys()
        ]

    def source_for_pipeline(self, config: LinkedinAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return linkedin_ads_source(
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

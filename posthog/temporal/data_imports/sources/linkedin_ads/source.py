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
from posthog.temporal.data_imports.sources.linkedin_ads.client import (
    LinkedinAdsAuthError,
    LinkedinAdsClient,
    LinkedinAdsError,
    LinkedinAdsRateLimitError,
)
from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import (
    get_incremental_fields as get_linkedin_ads_incremental_fields,
    get_schemas as get_linkedin_ads_schemas,
    linkedin_ads_source,
)
from posthog.temporal.data_imports.sources.linkedin_ads.utils.utils import validate_account_id
from posthog.warehouse.types import ExternalDataSourceType


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
        try:
            # Validate config structure
            if not config.account_id:
                return False, "Account ID is required"
            if not config.linkedin_ads_integration_id:
                return False, "LinkedIn Ads integration ID is required"

            # Validate account ID format
            if not validate_account_id(config.account_id):
                return False, f"Invalid account ID format: '{config.account_id}'. Should be numeric, 6-15 digits."

            # Get integration
            try:
                integration = Integration.objects.get(id=config.linkedin_ads_integration_id, team_id=team_id)
            except Integration.DoesNotExist:
                return (
                    False,
                    "LinkedIn Ads integration not found. Please re-authenticate or check your integration setup.",
                )

            if not integration.access_token:
                return False, "LinkedIn Ads access token not found. Please re-authenticate."

            # Test API access by fetching schemas (similar to Google Ads approach)
            try:
                schemas = self.get_schemas(config, team_id)
                if not schemas:
                    return False, "No schemas available. Please check your LinkedIn Ads account permissions."
            except LinkedinAdsAuthError as e:
                return False, f"LinkedIn authentication failed: {str(e)}"
            except LinkedinAdsRateLimitError as e:
                return False, f"LinkedIn rate limit exceeded during validation: {str(e)}"
            except LinkedinAdsError as e:
                return False, f"LinkedIn API error during validation: {str(e)}"
            except Exception as e:
                capture_exception(e)
                return False, f"Failed to validate schemas: {str(e)}"

            # Test basic API access
            client = LinkedinAdsClient(integration.access_token)
            accounts = client.get_accounts()

            # Verify the specified account exists
            account_ids = [str(acc.get("id")) for acc in accounts if acc.get("id")]
            if config.account_id not in account_ids:
                available_accounts = account_ids[:5]  # Show first 5 for debugging
                return (
                    False,
                    f"Account ID '{config.account_id}' not found in accessible accounts. Available: {available_accounts}",
                )

            return True, None

        except LinkedinAdsAuthError as e:
            return False, f"LinkedIn authentication failed: {str(e)}"
        except LinkedinAdsRateLimitError as e:
            return False, f"LinkedIn rate limit exceeded: {str(e)}"
        except LinkedinAdsError as e:
            return False, f"LinkedIn API error: {str(e)}"
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate LinkedIn Ads credentials: {str(e)}"

    def get_schemas(self, config: LinkedinAdsSourceConfig, team_id: int) -> list[SourceSchema]:
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

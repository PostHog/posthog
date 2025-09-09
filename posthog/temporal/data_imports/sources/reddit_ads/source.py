from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.generated_configs import RedditAdsSourceConfig
from posthog.temporal.data_imports.sources.reddit_ads.reddit_ads import reddit_ads_source
from posthog.temporal.data_imports.sources.reddit_ads.settings import (
    REDDIT_ADS_ENDPOINTS,
    REDDIT_ADS_INCREMENTAL_FIELDS,
)
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class RedditAdsSource(BaseSource[RedditAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDDITADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REDDIT_ADS,
            label="Reddit Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from Reddit Ads. Ensure you have granted PostHog access to your Reddit Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/reddit-ads).",
            betaSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Reddit Ads Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Reddit Ads account ID",
                    ),
                    SourceFieldOauthConfig(
                        name="reddit_integration_id",
                        label="Reddit Ads account",
                        required=True,
                        kind="reddit-ads",
                    ),
                ],
            ),
        )

    def validate_credentials(self, config: RedditAdsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.account_id or not config.reddit_integration_id:
            return False, "Account ID and Reddit Ads integration are required"

        try:
            Integration.objects.get(id=config.reddit_integration_id, team_id=team_id)
            return True, None
        except Integration.DoesNotExist:
            return False, "Reddit Ads integration not found. Please re-authenticate."
        except Exception as e:
            from posthog.exceptions_capture import capture_exception

            capture_exception(e)
            return False, f"Failed to validate Reddit Ads credentials: {str(e)}"

    def get_schemas(self, config: RedditAdsSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=REDDIT_ADS_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=REDDIT_ADS_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=REDDIT_ADS_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in REDDIT_ADS_ENDPOINTS
        ]

    def source_for_pipeline(self, config: RedditAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            reddit_ads_source(
                account_id=config.account_id,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                reddit_integration_id=config.reddit_integration_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )

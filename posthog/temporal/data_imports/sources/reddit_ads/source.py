from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import RedditAdsSourceConfig
from posthog.temporal.data_imports.sources.reddit_ads.reddit_ads import reddit_ads_source
from posthog.temporal.data_imports.sources.reddit_ads.settings import REDDIT_ADS_CONFIG
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class RedditAdsSource(BaseSource[RedditAdsSourceConfig], OAuthMixin):
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
            iconPath="/static/services/reddit.png",
            docsUrl="https://posthog.com/docs/cdp/sources/reddit-ads",
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
            self.get_oauth_integration(config.reddit_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Reddit Ads credentials: {str(e)}"

    def get_schemas(self, config: RedditAdsSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=str(endpoint_config.resource["name"]),
                supports_incremental=endpoint_config.incremental_fields is not None,
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields or [],
            )
            for endpoint_config in REDDIT_ADS_CONFIG.values()
        ]

    def source_for_pipeline(self, config: RedditAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.reddit_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Reddit Ads access token not found for job {inputs.job_id}")

        return reddit_ads_source(
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            access_token=integration.access_token,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import GoogleAnalyticsSourceConfig
from posthog.temporal.data_imports.sources.google_analytics.google_analytics import (
    get_schemas as get_google_analytics_schemas,
    google_analytics_source,
    validate_credentials as validate_google_analytics_credentials,
)
from posthog.temporal.data_imports.sources.google_analytics.settings import (
    INCREMENTAL_FIELDS as GOOGLE_ANALYTICS_INCREMENTAL_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleAnalyticsSource(SimpleSource[GoogleAnalyticsSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLE_ANALYTICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_ANALYTICS,
            label="Google Analytics",
            caption="Import data from Google Analytics 4 properties. You'll need to provide your property ID and authenticate with Google.",
            iconPath="/static/services/google-analytics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-analytics",
            feature_flag="dwh_google_analytics",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="property_id",
                        label="Property ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456789",
                    ),
                    SourceFieldOauthConfig(
                        name="google_analytics_integration_id",
                        label="Google Analytics account",
                        required=True,
                        kind="google-analytics",
                    ),
                ],
            ),
        )

    def validate_credentials(self, config: GoogleAnalyticsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_google_analytics_credentials(config, team_id):
                return True, None
            else:
                return False, "Invalid Google Analytics credentials"
        except Exception as e:
            return False, str(e)

    def get_schemas(
        self, config: GoogleAnalyticsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        google_analytics_schemas = get_google_analytics_schemas(config, team_id)

        return [
            SourceSchema(
                name=schema_name,
                supports_incremental=GOOGLE_ANALYTICS_INCREMENTAL_FIELDS.get(schema_name, None) is not None,
                supports_append=GOOGLE_ANALYTICS_INCREMENTAL_FIELDS.get(schema_name, None) is not None,
                incremental_fields=GOOGLE_ANALYTICS_INCREMENTAL_FIELDS.get(schema_name, []),
            )
            for schema_name in google_analytics_schemas
        ]

    def source_for_pipeline(
        self, config: GoogleAnalyticsSourceConfig, inputs: SourceInputs
    ) -> SourceResponse:
        return google_analytics_source(
            config=config,
            schema_name=inputs.schema_name,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

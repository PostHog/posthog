from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SuggestedTable,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import RevenueCatSourceConfig
from posthog.temporal.data_imports.sources.revenuecat.revenuecat import (
    revenuecat_source,
    validate_revenuecat_credentials,
)
from posthog.temporal.data_imports.sources.revenuecat.settings import (
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    REVENUECAT_ENDPOINTS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RevenueCatSource(SimpleSource[RevenueCatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REVENUECAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REVENUE_CAT,
            caption="""Enter your RevenueCat credentials to automatically pull your RevenueCat data into the PostHog Data warehouse. You will need your [RevenueCat API key](https://app.revenuecat.com/api-keys) and your [Project ID](https://app.revenuecat.com/overview).""",
            permissionsCaption="""Your API key needs read-only permissions for the entities you want to sync.""",
            label="RevenueCat",
            iconPath="/static/services/revenuecat.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="revenuecat_api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                    ),
                    SourceFieldInputConfig(
                        name="revenuecat_project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="proj1ab2c3d4",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="App",
                    tooltip="If you have multiple apps, you can enable this to get data for all apps.",
                ),
                SuggestedTable(
                    table="Customer",
                    tooltip="Enable this to get all your in-app customer data in PostHog.",
                ),
                SuggestedTable(
                    table="Entitlement",
                    tooltip="Enable this to get all your entitlement data in PostHog.",
                ),
                SuggestedTable(
                    table="Offering",
                    tooltip="Enable this to get all your offering data in PostHog.",
                ),
                SuggestedTable(
                    table="Product",
                    tooltip="Enable this to get all your product information in PostHog.",
                ),
            ],
            betaSource=True,
            featureFlag="dp-source-revenuecat",
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400": "Client error.",
            "401": "Not authenticated. Please check your API key configuration and permissions in RevenueCat, then try again.",
            "403": "uthorization failed. Please check your API key configuration and permissions in RevenueCat, then try again.",
            "404": "No resource was found. Please check the resource name and try again.",
            "409": "Uniqueness constraint violation. Please check the request body and try again.",
            "422": "The request was valid and the syntax correct, but RC was unable to process the contained instructions. Please check the request body and try again.",
        }

    def get_schemas(
        self, config: RevenueCatSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_ENDPOINTS,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in REVENUECAT_ENDPOINTS
        ]

    def validate_credentials(self, config: RevenueCatSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_revenuecat_credentials(config.revenuecat_api_key, config.revenuecat_project_id):
                return True, None
            else:
                return False, "Invalid RevenueCat credentials"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: RevenueCatSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return revenuecat_source(
            api_key=config.revenuecat_api_key,
            project_id=config.revenuecat_project_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

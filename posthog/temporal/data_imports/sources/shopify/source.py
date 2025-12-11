from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import ShopifyIntegration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import ShopifySourceConfig
from posthog.temporal.data_imports.sources.shopify.constants import SHOPIFY_GRAPHQL_OBJECTS
from posthog.temporal.data_imports.sources.shopify.settings import ENDPOINT_CONFIGS
from posthog.temporal.data_imports.sources.shopify.shopify import (
    ShopifyPermissionError,
    shopify_source,
    validate_credentials as validate_shopify_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShopifySource(SimpleSource[ShopifySourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHOPIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHOPIFY,
            iconPath="/static/services/shopify.png",
            caption="""Enter your Shopify credentials to automatically pull your Shopify data into the PostHog data warehouse.""",
            docsUrl="https://posthog.com/docs/data-warehouse/sources/shopify",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="shopify_integration_id",
                        label="Shopify integration",
                        required=True,
                        kind="shopify",
                    ),
                ],
            ),
            betaSource=True,
            featureFlag="shopify-dwh",
        )

    def validate_credentials(self, config: ShopifySourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.shopify_integration_id:
            return False, "Shopify integration is required"

        try:
            integration = self.get_oauth_integration(config.shopify_integration_id, team_id)
            shopify = ShopifyIntegration(integration)
            shopify_access_token = shopify.get_access_token()
            if not shopify_access_token:
                raise ValueError(
                    f"Shopify access token not found for: integration={config.shopify_integration_id} team={team_id}"
                )
            if validate_shopify_credentials(shopify.shop, shopify_access_token):
                return True, None
            return False, "Invalid Shopify credentials"
        except ShopifyPermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"Shopify access token lacks permissions for {missing_resources}"
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Shopify credentials: {str(e)}"

    def get_schemas(self, config: ShopifySourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas = []
        for obj in SHOPIFY_GRAPHQL_OBJECTS.values():
            endpoint_config = ENDPOINT_CONFIGS.get(obj.name)
            if not endpoint_config:
                raise ValueError(f"No endpoint config found for {obj.name}")
            schemas.append(
                SourceSchema(
                    name=obj.display_name or obj.name,
                    supports_incremental=len(endpoint_config.fields) > 0,
                    supports_append=len(endpoint_config.fields) > 0,
                    incremental_fields=endpoint_config.fields,
                )
            )
        return schemas

    def source_for_pipeline(self, config: ShopifySourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.shopify_integration_id, inputs.team_id)
        shopify = ShopifyIntegration(integration)
        access_token = shopify.get_access_token()

        if not access_token:
            raise ValueError(f"Shopify access token not found for job {inputs.job_id}")

        return shopify_source(
            shopify_store_id=shopify.shop,
            shopify_access_token=access_token,
            graphql_object_name=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )

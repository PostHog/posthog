from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import ShopifySourceConfig
from posthog.temporal.data_imports.sources.shopify.constants import SHOPIFY_GRAPHQL_OBJECTS
from posthog.temporal.data_imports.sources.shopify.settings import INCREMENTAL_SETTINGS
from posthog.temporal.data_imports.sources.shopify.shopify import (
    ShopifyPermissionError,
    shopify_source,
    validate_credentials as validate_shopify_credentials,
)
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class ShopifySource(BaseSource[ShopifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHOPIFY

    # TODO:andrew to write docs for setting up private access token
    # TODO:andrew to update the "follow these steps" URL in doc string
    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHOPIFY,
            iconPath="/static/services/shopify.png",
            caption="""Enter your Shopify credentials to automatically pull your Shopify data into the PostHog Data warehouse.

You can find your store id by visiting your store's admin console. Your store id will be included in the store URL which typically looks something like _https://{store-id}.myshopify.com_.

To create and configure your access token go to [your store's admin console](https://admin.shopify.com) and [follow these steps]().

The simplest setup for permissions is to only allow **read** permissions for the resources you are interested in syncing with your warehouse.
        """,
            docsUrl="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="shopify_store_id",
                        label="Store id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-store-id",
                    ),
                    SourceFieldInputConfig(
                        name="shopify_access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="shpat_...",
                    ),
                ],
            ),
            unreleasedSource=True,
            betaSource=True,
            featureFlag="shopify-dwh",
        )

    def validate_credentials(self, config: ShopifySourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_shopify_credentials(config.shopify_store_id, config.shopify_access_token):
                return True, None
            return False, "Invalid Shopify credentials"
        except ShopifyPermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"Shopify access token lacks permissions for {missing_resources}"
        except Exception as e:
            return False, str(e)

    def get_schemas(self, config: ShopifySourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas = []
        for object_name in SHOPIFY_GRAPHQL_OBJECTS:
            incremental = INCREMENTAL_SETTINGS.get(object_name)
            incremental_fields = incremental.fields if incremental else []
            schemas.append(
                SourceSchema(
                    name=object_name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                )
            )
        return schemas

    def source_for_pipeline(self, config: ShopifySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return shopify_source(
            shopify_store_id=config.shopify_store_id,
            shopify_access_token=config.shopify_access_token,
            graphql_object_name=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )

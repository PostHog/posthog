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
from posthog.temporal.data_imports.sources.shopify.shopify import (
    ShopifyPermissionError,
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

You can find your store URL by visiting your store's admin console. The URL typically looks like https://{store_id}.myshopify.com OR https://shop.{store_id}.com. To create and configure your access token go to [your store's admin console](https://admin.shopify.com) and [follow these steps]()

The simplest setup for permissions is to only allow **read** permissions for the resources you are interested in syncing with your warehouse.
        """,
            docsUrl="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="shopify_store_url",
                        label="Store URL",
                        type=SourceFieldInputConfigType.URL,
                        required=True,
                        # we will parse and validate this URL in the source implementation
                        placeholder="https://my-store-id.myshopify.com",
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
        raise NotImplementedError()

    def source_for_pipeline(self, config: ShopifySourceConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()

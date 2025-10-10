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
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class ShopifySource(BaseSource[ShopifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHOPIFY

    # TODO:andrew to write docs for setting up private access token
    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHOPIFY,
            caption="""Enter your Shopify credentials to automatically pull your Shopify data into the PostHog Data warehouse.

You can find your store ID in your store's URL which typically looks like https://shop.{store_id}.com. To create and configure your access token go to [your store's admin panel](https://admin.shopify.com) and [follow these steps]()

The simplest setup for permissions is to only allow **read** permissions for the resources you are interested in syncing with your warehouse.
""",
            iconPath="/static/services/stripe.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shopify",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="shopify_store_id",
                        label="Store id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="shopify_store_id",
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

    def get_schemas(self, config: ShopifySourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        raise NotImplementedError()

    def validate_credentials(self, config: ShopifySourceConfig, team_id: int) -> tuple[bool, str | None]:
        raise NotImplementedError()

    def source_for_pipeline(self, config: ShopifySourceConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()

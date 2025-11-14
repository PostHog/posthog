from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SquareSourceConfig
from posthog.temporal.data_imports.sources.square.settings import (
    ENDPOINTS as SQUARE_ENDPOINTS,
    INCREMENTAL_FIELDS as SQUARE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.square.square import (
    SquarePermissionError,
    square_source,
    validate_credentials as validate_square_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SquareSource(SimpleSource[SquareSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SQUARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SQUARE,
            caption="""Enter your Square credentials to automatically pull your Square data into the PostHog Data warehouse.

You can create an access token by logging into your Square Developer account, creating an application, and generating either a Personal Access Token or using OAuth 2.0.

To create a Personal Access Token:
1. Go to the [Square Developer Dashboard](https://developer.squareup.com/apps)
2. Create or select an application
3. Navigate to the "OAuth" section
4. Generate a Personal Access Token with the required permissions

Currently, **read permissions are recommended** for the following resources:

- **Payments** - View payment transactions
- **Customers** - View customer information
- **Orders** - View order details
- **Items & Inventory** - View catalog items, categories, discounts, taxes, and inventory levels
- **Team** - View team member information and shift data
- **Merchant** - View location information

For production use, create a production access token. For testing, you can use a sandbox access token.
""",
            iconPath="/static/services/square.png",
            docsUrl="https://posthog.com/docs/cdp/sources/square",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="square_access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="EAAAl...",
                    ),
                ],
            ),
            featureFlag="dwh_square",
        )

    def get_schemas(self, config: SquareSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=SQUARE_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=SQUARE_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in SQUARE_ENDPOINTS
        ]

    def validate_credentials(self, config: SquareSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_square_credentials(config.square_access_token):
                return True, None
            else:
                return False, "Invalid Square credentials"
        except SquarePermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"Square access token lacks permissions for {missing_resources}"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: SquareSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return square_source(
            access_token=config.square_access_token,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )

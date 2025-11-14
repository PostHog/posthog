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
from posthog.temporal.data_imports.sources.drip.drip import drip_source, validate_credentials
from posthog.temporal.data_imports.sources.drip.settings import ENDPOINTS as DRIP_ENDPOINTS
from posthog.temporal.data_imports.sources.drip.settings import INCREMENTAL_FIELDS as DRIP_INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.generated_configs import DripSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DripSource(SimpleSource[DripSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRIP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DRIP,
            label="Drip",
            caption="""Enter your Drip credentials to automatically pull your Drip data into the PostHog Data warehouse.

You can find your API token in your [Drip account settings](https://www.getdrip.com/user/edit) under the "API Token" section.

Your account ID can be found in your Drip dashboard URL (e.g., https://www.getdrip.com/12345678/dashboard - the number is your account ID).
""",
            iconPath="/static/services/drip.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/drip",
            feature_flag="dwh_drip",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345678",
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your_api_token",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: DripSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=DRIP_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=DRIP_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in DRIP_ENDPOINTS
        ]

    def validate_credentials(self, config: DripSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_credentials(config.api_token, config.account_id):
                return True, None
            else:
                return False, "Invalid Drip credentials. Please check your API token and account ID."
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: DripSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return drip_source(
            api_token=config.api_token,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )

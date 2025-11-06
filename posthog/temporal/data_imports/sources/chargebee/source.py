import re
from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.chargebee.chargebee import (
    chargebee_source,
    validate_credentials as validate_chargebee_credentials,
)
from posthog.temporal.data_imports.sources.chargebee.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.generated_configs import ChargebeeSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChargebeeSource(SimpleSource[ChargebeeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARGEBEE

    def get_schemas(self, config: ChargebeeSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(self, config: ChargebeeSourceConfig, team_id: int) -> tuple[bool, str | None]:
        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if not subdomain_regex.match(config.site_name):
            return False, "Chargebee site name is incorrect"

        if validate_chargebee_credentials(config.api_key, config.site_name):
            return True, None

        return False, "Invalid credentials"

    def source_for_pipeline(self, config: ChargebeeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            chargebee_source(
                api_key=config.api_key,
                site_name=config.site_name,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHARGEBEE,
            docsUrl="https://posthog.com/docs/cdp/sources/chargebee",
            iconPath="/static/services/chargebee.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="site_name",
                        label="Site name (subdomain)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                ],
            ),
        )

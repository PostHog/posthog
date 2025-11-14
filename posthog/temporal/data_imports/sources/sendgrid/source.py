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
from posthog.temporal.data_imports.sources.generated_configs import SendgridSourceConfig
from posthog.temporal.data_imports.sources.sendgrid.sendgrid import (
    sendgrid_source,
    validate_credentials as validate_sendgrid_credentials,
)
from posthog.temporal.data_imports.sources.sendgrid.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SendgridSource(SimpleSource[SendgridSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENDGRID

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SENDGRID,
            label="Sendgrid",
            iconPath="/static/services/sendgrid.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/sendgrid",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="SG.xxxxxxxxxxxxxxxxxxxxx",
                    ),
                ],
            ),
            featureFlag="dwh_sendgrid",
        )

    def validate_credentials(self, config: SendgridSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if validate_sendgrid_credentials(config.api_key):
            return True, None

        return False, "Invalid API key"

    def get_schemas(self, config: SendgridSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def source_for_pipeline(self, config: SendgridSourceConfig, inputs: SourceInputs) -> SourceResponse:
        source = sendgrid_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

        return SourceResponse(
            items=source,
            primary_keys=self._get_primary_keys(inputs.schema_name),
            partition_keys=self._get_partition_keys(inputs.schema_name),
            partition_mode=self._get_partition_mode(inputs.schema_name),
        )

    def _get_primary_keys(self, schema_name: str) -> list[str]:
        primary_keys_map = {
            "campaigns": ["id"],
            "lists": ["id"],
            "contacts": ["id"],
            "segments": ["id"],
            "singlesends": ["id"],
            "templates": ["id"],
            "global_suppressions": ["email"],
            "suppression_groups": ["id"],
            "suppression_group_members": ["group_id", "email"],
            "blocks": ["email"],
            "bounces": ["email"],
            "invalid_emails": ["email"],
            "spam_reports": ["email"],
        }
        return primary_keys_map.get(schema_name, ["id"])

    def _get_partition_keys(self, schema_name: str) -> list[str] | None:
        if schema_name in INCREMENTAL_FIELDS:
            incremental_field = INCREMENTAL_FIELDS[schema_name][0]["field"]
            return [incremental_field]
        return None

    def _get_partition_mode(self, schema_name: str) -> str | None:
        if schema_name in INCREMENTAL_FIELDS:
            return "datetime"
        return None

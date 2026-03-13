from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.attio.attio import (
    attio_source,
    validate_credentials as validate_attio_credentials,
)
from posthog.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import AttioSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AttioSource(SimpleSource[AttioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ATTIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.attio.com": "Your Attio API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.attio.com": "Your Attio API key does not have the required scopes. Please check the API key permissions and try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ATTIO,
            caption="""Enter your Attio API key to automatically pull your Attio data into the PostHog Data warehouse.

You can generate an API key in your Attio workspace settings. Check out [this guide](https://attio.com/help/apps/other-apps/generating-an-api-key) for more details.

**Required API scopes:**
- `object_configuration:read` - To read object configurations
- `record_permission:read` - To read record permissions
- `record:read` - To read records (companies, people, deals, users, workspaces)
- `list_entry:read` - To read list entries
- `note:read` - To read notes
- `task:read` - To read tasks
- `user_management:read` - To read workspace members
""",
            iconPath="/static/services/attio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/attio",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your Attio API key",
                    ),
                ],
            ),
            featureFlag="dwh_attio",
        )

    def get_schemas(self, config: AttioSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        # Attio API doesn't support updatedAt filtering, so only full refresh is supported
        return [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint_config in ATTIO_ENDPOINTS.values()
        ]

    def validate_credentials(
        self, config: AttioSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_attio_credentials(config.api_key)

    def source_for_pipeline(self, config: AttioSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return attio_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

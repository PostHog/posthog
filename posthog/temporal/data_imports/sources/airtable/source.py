from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.airtable.airtable import (
    airtable_source,
    validate_credentials as validate_airtable_credentials,
)
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import AirtableSourceConfig
from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AirtableSource(SimpleSource[AirtableSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRTABLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AIRTABLE,
            iconPath="/static/services/airtable.png",
            label="Airtable",
            caption="""Connect your Airtable bases to PostHog's Data warehouse.

You'll need a [Personal Access Token](https://airtable.com/create/tokens) with the following scopes:
- `data.records:read` - to read records from your tables
- `schema.bases:read` - to discover bases and tables

Once connected, PostHog will automatically discover all tables in your accessible bases.""",
            docsUrl="https://posthog.com/docs/cdp/sources/airtable",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="patXXXXXXXXXXXXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
                    ),
                ],
            ),
            featureFlag="dwh_airtable",
        )

    def validate_credentials(self, config: AirtableSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            access_token = config.access_token
            if not access_token:
                return False, "Access token is required"

            from structlog import get_logger

            logger = get_logger()

            if validate_airtable_credentials(access_token, logger):
                return True, None
            else:
                return False, "Invalid Airtable credentials or insufficient permissions"
        except Exception as e:
            return False, str(e)

    def get_schemas(self, config: AirtableSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        """Discover all tables from all accessible Airtable bases."""
        try:
            access_token = config.access_token
            if not access_token:
                return []

            from structlog import get_logger

            from posthog.temporal.data_imports.sources.airtable.airtable import AirtableClient

            logger = get_logger()
            client = AirtableClient(access_token, logger)

            schemas = []
            bases = client.list_bases()

            for base in bases:
                base_id = base.get("id")
                base_name = base.get("name", base_id)

                try:
                    base_schema = client.get_base_schema(base_id)
                    tables = base_schema.get("tables", [])

                    for table in tables:
                        table_name = table.get("name")
                        # Create a unique schema name combining base and table
                        # Format: baseName_tableName (e.g., "Marketing_Contacts")
                        schema_name = f"{base_name}_{table_name}"

                        schemas.append(
                            SourceSchema(
                                name=schema_name,
                                supports_incremental=False,
                                supports_append=False,
                                incremental_fields=[],
                            )
                        )
                except Exception as e:
                    logger.warning(f"Airtable: failed to get schema for base {base_id}", error=str(e))
                    continue

            return schemas
        except Exception as e:
            from structlog import get_logger

            logger = get_logger()
            logger.error(f"Airtable: failed to get schemas", error=str(e))
            return []

    def source_for_pipeline(self, config: AirtableSourceConfig, inputs: SourceInputs) -> SourceResponse:
        access_token = config.access_token
        if not access_token:
            raise ValueError("Access token is required")

        # Parse the schema_name to extract base name and table name
        # Format: baseName_tableName
        schema_name = inputs.schema_name
        parts = schema_name.split("_", 1)

        if len(parts) != 2:
            raise ValueError(f"Invalid schema name format: {schema_name}. Expected format: baseName_tableName")

        base_name, table_name = parts

        # Get the base ID from the base name
        from posthog.temporal.data_imports.sources.airtable.airtable import AirtableClient

        client = AirtableClient(access_token, inputs.logger)
        bases = client.list_bases()

        base_id = None
        for base in bases:
            if base.get("name") == base_name:
                base_id = base.get("id")
                break

        if not base_id:
            raise ValueError(f"Base not found: {base_name}")

        return airtable_source(
            access_token=access_token,
            base_id=base_id,
            table_name=table_name,
            logger=inputs.logger,
        )

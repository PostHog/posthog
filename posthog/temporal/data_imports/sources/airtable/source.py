from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.airtable.airtable import (
    AirtableAPIError,
    airtable_source,
    list_bases,
    list_tables,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.airtable.settings import get_incremental_field_for_table
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
            caption="""Enter your Airtable Personal Access Token to automatically pull your Airtable data into the PostHog Data warehouse.

You can create a Personal Access Token in your [Airtable account settings](https://airtable.com/create/tokens).

**Required token scopes:**
- `data.records:read` - Read records from tables
- `schema.bases:read` - Read base and table schemas

Optionally, you can specify a Base ID to sync only tables from that specific base. If left empty, all accessible bases will be synced.
""",
            iconPath="/static/services/airtable.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/airtable",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal Access Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="patXXXXXXXXXXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
                    ),
                    SourceFieldInputConfig(
                        name="base_id",
                        label="Base ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="appXXXXXXXXXXXXXX",
                    ),
                ],
            ),
            featureFlag="dwh_airtable",
        )

    def validate_credentials(self, config: AirtableSourceConfig, team_id: int) -> tuple[bool, str | None]:
        """Validate Airtable credentials by attempting to list bases"""
        try:
            if validate_credentials(config.access_token, self.get_logger()):
                return True, None
            else:
                return False, "Invalid Airtable credentials or insufficient permissions"
        except AirtableAPIError as e:
            return False, f"Airtable API error: {str(e)}"
        except Exception as e:
            return False, f"Error validating credentials: {str(e)}"

    def get_schemas(self, config: AirtableSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        """Get all available schemas (tables) from Airtable bases"""
        logger = self.get_logger()
        schemas: list[SourceSchema] = []

        try:
            if config.base_id:
                bases = [{"id": config.base_id, "name": config.base_id}]
                logger.info(f"Using specified base_id: {config.base_id}")
            else:
                bases = list_bases(config.access_token, logger)

            for base in bases:
                base_id = base["id"]
                base_name = base.get("name", base_id)

                try:
                    tables = list_tables(base_id, config.access_token, logger)

                    for table in tables:
                        table_id = table["id"]
                        table_name = table.get("name", table_id)
                        schema_name = f"{base_name}__{table_name}"

                        schemas.append(
                            SourceSchema(
                                name=schema_name,
                                supports_incremental=True,
                                supports_append=True,
                                incremental_fields=get_incremental_field_for_table(),
                            )
                        )
                except Exception as e:
                    logger.error(f"Error fetching tables for base {base_id}: {e}")
                    continue

            logger.info(f"Found {len(schemas)} schemas across {len(bases)} bases")
            return schemas

        except Exception as e:
            logger.error(f"Error getting schemas: {e}")
            raise

    def source_for_pipeline(self, config: AirtableSourceConfig, inputs: SourceInputs) -> SourceResponse:
        """
        Create a source for the pipeline to sync data from Airtable.

        The schema_name format is: {base_name}__{table_name}
        We parse this to extract the base and table information.
        """
        logger = inputs.logger

        try:
            schema_parts = inputs.schema_name.split("__", 1)
            if len(schema_parts) != 2:
                raise ValueError(f"Invalid schema name format: {inputs.schema_name}. Expected 'base_name__table_name'")

            base_name, table_name = schema_parts

            if config.base_id:
                base_id = config.base_id
            else:
                bases = list_bases(config.access_token, logger)
                matching_base = next((b for b in bases if b.get("name") == base_name), None)
                if not matching_base:
                    raise ValueError(f"Base not found: {base_name}")
                base_id = matching_base["id"]

            tables = list_tables(base_id, config.access_token, logger)
            matching_table = next((t for t in tables if t.get("name") == table_name), None)
            if not matching_table:
                raise ValueError(f"Table not found: {table_name} in base {base_id}")

            table_id = matching_table["id"]

            logger.info(f"Syncing base={base_id}, table={table_id} ({table_name})")

            records_iterator = airtable_source(
                access_token=config.access_token,
                base_id=base_id,
                table_id=table_id,
                logger=logger,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            )

            return SourceResponse(
                items=records_iterator,
                primary_keys=["id"],
                partition_keys=["createdTime"],
                partition_mode="datetime",
                partition_format="month",
            )

        except Exception as e:
            logger.error(f"Error creating source for pipeline: {e}")
            raise

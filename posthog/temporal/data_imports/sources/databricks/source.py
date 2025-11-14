from typing import cast

from databricks.sql.exc import Error as DatabricksError

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import DatabricksSourceConfig
from posthog.temporal.data_imports.sources.databricks.databricks import (
    filter_databricks_incremental_fields,
    get_schemas as get_databricks_schemas,
    databricks_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField

DatabricksErrors = {
    "Invalid access token": "Invalid access token. Please check your personal access token.",
    "Warehouse": "Could not connect to SQL warehouse. Please check your HTTP path.",
    "does not exist": "Catalog or schema does not exist. Please check your catalog and schema names.",
}


@SourceRegistry.register
class DatabricksSource(SimpleSource[DatabricksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATABRICKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DATABRICKS,
            caption="Enter your Databricks credentials to automatically pull your Databricks data into the PostHog Data warehouse.",
            iconPath="/static/services/databricks.png",
            docsUrl="https://posthog.com/docs/cdp/sources/databricks",
            feature_flag="dwh_databricks",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="server_hostname",
                        label="Server hostname",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="dbc-a1b2c3d4-e5f6.cloud.databricks.com",
                    ),
                    SourceFieldInputConfig(
                        name="http_path",
                        label="HTTP path",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="/sql/1.0/warehouses/abc123def456",
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="dapi...",
                    ),
                    SourceFieldInputConfig(
                        name="catalog",
                        label="Catalog",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="main",
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="default",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: DatabricksSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas = []

        db_schemas = get_databricks_schemas(config)

        for table_name, columns in db_schemas.items():
            column_info = [(col_name, col_type) for col_name, col_type in columns]

            incremental_field_tuples = filter_databricks_incremental_fields(column_info)
            incremental_fields: list[IncrementalField] = [
                {
                    "label": field_name,
                    "type": field_type,
                    "field": field_name,
                    "field_type": field_type,
                }
                for field_name, field_type in incremental_field_tuples
            ]

            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                )
            )

        return schemas

    def validate_credentials(self, config: DatabricksSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.server_hostname or not config.http_path or not config.access_token:
            return False, "Missing required parameters: server hostname, HTTP path, or access token"

        if not config.catalog or not config.schema:
            return False, "Missing required parameters: catalog or schema"

        try:
            self.get_schemas(config, team_id)
        except DatabricksError as e:
            error_msg = str(e)
            for key, value in DatabricksErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to Databricks. Please check all connection details are valid."
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to Databricks. Please check all connection details are valid."

        return True, None

    def source_for_pipeline(self, config: DatabricksSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return databricks_source(
            server_hostname=config.server_hostname,
            http_path=config.http_path,
            access_token=config.access_token,
            catalog=config.catalog,
            schema=config.schema,
            table_names=[inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

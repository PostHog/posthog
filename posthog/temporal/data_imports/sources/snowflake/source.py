from typing import TYPE_CHECKING
from snowflake.connector.errors import DatabaseError, ForbiddenError, ProgrammingError
from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.snowflake.snowflake import (
    get_schemas as get_snowflake_schemas,
    filter_snowflake_incremental_fields,
    snowflake_source,
)
from posthog.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
from posthog.warehouse.types import IncrementalField

if TYPE_CHECKING:
    from posthog.warehouse.models import ExternalDataSource

SnowflakeErrors = {
    "No active warehouse selected in the current session": "No warehouse found for selected role",
    "or attempt to login with another role": "Role specified doesn't exist or is not authorized",
    "Incorrect username or password was specified": "Incorrect username or password was specified",
    "This session does not have a current database": "Database specified not found",
    "Verify the account name is correct": "Can't find an account with the specified account ID",
}


@SourceRegistry.register
class SnowflakeSource(BaseSource[SnowflakeSourceConfig]):
    @property
    def source_type(self) -> "ExternalDataSource.Type":
        from posthog.warehouse.models import ExternalDataSource

        return ExternalDataSource.Type.SNOWFLAKE

    def get_schemas(self, config: SnowflakeSourceConfig, team_id: int) -> list[SourceSchema]:
        schemas = []

        # TODO: fix config in snowflake source
        db_schemas = get_snowflake_schemas(config)

        for table_name, columns in db_schemas.items():
            column_info = [(col_name, col_type) for col_name, col_type in columns]

            incremental_field_tuples = filter_snowflake_incremental_fields(column_info)
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

    def validate_credentials(self, config: SnowflakeSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if config.auth_type.selection == "password" and (not config.auth_type.user or not config.auth_type.password):
            return False, "Missing required parameters: username, password"

        if config.auth_type.selection == "keypair" and (
            not config.auth_type.passphrase or not config.auth_type.private_key or not config.auth_type.user
        ):
            return False, "Missing required parameters: passphrase, private key"

        try:
            self.get_schemas(config, team_id)
        except (ProgrammingError, DatabaseError, ForbiddenError) as e:
            error_msg = e.msg or e.raw_msg or ""
            for key, value in SnowflakeErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to Snowflake. Please check all connection details are valid."
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to Snowflake. Please check all connection details are valid."

        return True, None

    def source_for_pipeline(self, config: SnowflakeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return snowflake_source(
            account_id=config.account_id,
            user=config.auth_type.user,
            password=config.auth_type.password,
            passphrase=config.auth_type.passphrase,
            private_key=config.auth_type.private_key,
            auth_type=config.auth_type.selection,
            database=config.database,
            warehouse=config.warehouse,
            schema=config.schema,
            role=config.role,
            table_names=[inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

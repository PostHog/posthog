from typing import Optional, cast

import structlog
from snowflake.connector.errors import DatabaseError, ForbiddenError, ProgrammingError

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
from posthog.temporal.data_imports.sources.snowflake.snowflake import (
    filter_snowflake_incremental_fields,
    get_leading_clustering_columns_for_schemas as get_snowflake_leading_clustering_columns_for_schemas,
    get_primary_keys_for_schemas as get_snowflake_primary_keys_for_schemas,
    get_schemas as get_snowflake_schemas,
    snowflake_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField

SnowflakeErrors = {
    "No active warehouse selected in the current session": "No warehouse found for selected role",
    "or attempt to login with another role": "Role specified doesn't exist or is not authorized",
    "Incorrect username or password was specified": "Incorrect username or password was specified",
    "This session does not have a current database": "Database specified not found",
    "Verify the account name is correct": "Can't find an account with the specified account ID",
}


@SourceRegistry.register
class SnowflakeSource(SimpleSource[SnowflakeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNOWFLAKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SNOWFLAKE,
            caption="Enter your Snowflake credentials to automatically pull your Snowflake data into the PostHog Data warehouse.",
            iconPath="/static/services/snowflake.png",
            docsUrl="https://posthog.com/docs/cdp/sources/snowflake",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="snowflake://user:password@account_id/database/schema?warehouse=COMPUTE_WAREHOUSE&role=ACCOUNTADMIN",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="snowflake_sample_data",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="warehouse",
                        label="Warehouse",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="COMPUTE_WAREHOUSE",
                        secret=False,
                    ),
                    # the validation for these options happens in validate_credentials
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication type",
                        required=True,
                        defaultValue="password",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Password",
                                value="password",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="User1",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="password",
                                            label="Password",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Key pair",
                                value="keypair",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="User1",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="private_key",
                                            label="Private key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="passphrase",
                                            label="Passphrase",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="role",
                        label="Role (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="ACCOUNTADMIN",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="public",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "This account has been marked for decommission": "Your Snowflake account has been suspended or trial has ended. Please check your account status.",
            "404 Not Found": None,
            "Your free trial has ended": "Your Snowflake account has been suspended or trial has ended. Please check your account status.",
            "Your account is suspended due to lack of payment method": "Your Snowflake account has been suspended or trial has ended. Please check your account status.",
            "MFA authentication is required": None,
            "invalid credentials": "Snowflake authentication failed. Please check your username, password, and account details.",
            "authentication failed": "Snowflake authentication failed. Please check your username, password, and account details.",
        }

    def get_schemas(
        self, config: SnowflakeSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = []

        db_schemas = get_snowflake_schemas(config, names=names)
        try:
            detected_pks = get_snowflake_primary_keys_for_schemas(
                config=config,
                table_names=list(db_schemas.keys()),
            )
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for Snowflake schemas", exc_info=e)
            detected_pks = {}

        indexed_columns_by_table = get_snowflake_leading_clustering_columns_for_schemas(
            config=config,
            table_names=list(db_schemas.keys()),
        )

        for table_name, columns in db_schemas.items():
            incremental_field_tuples = filter_snowflake_incremental_fields(columns)
            indexed_cols = indexed_columns_by_table.get(table_name) if indexed_columns_by_table is not None else None
            incremental_fields: list[IncrementalField] = [
                {
                    "label": field_name,
                    "type": field_type,
                    "field": field_name,
                    "field_type": field_type,
                    "nullable": nullable,
                    "is_indexed": True if indexed_cols is None else field_name in indexed_cols,
                }
                for field_name, field_type, nullable in incremental_field_tuples
            ]

            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                    columns=columns,
                    detected_primary_keys=detected_pks.get(table_name),
                )
            )

        return schemas

    def validate_credentials(
        self, config: SnowflakeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if config.auth_type.selection == "password" and (not config.auth_type.user or not config.auth_type.password):
            return False, "Missing required parameters: username, password"

        # passphrase is optional if the key they use to auth is not encrypted
        if config.auth_type.selection == "keypair" and (not config.auth_type.user or not config.auth_type.private_key):
            return False, "Missing required parameters: username, private key"

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

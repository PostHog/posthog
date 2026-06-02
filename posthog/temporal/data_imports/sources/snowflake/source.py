from typing import Optional, cast

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
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
from posthog.temporal.data_imports.sources.snowflake.snowflake import SnowflakeImplementation

from products.data_warehouse.backend.types import ExternalDataSourceType

_SNOWFLAKE_IMPLEMENTATION = SnowflakeImplementation()

SnowflakeErrors = {
    "No active warehouse selected in the current session": "No warehouse found for selected role",
    "or attempt to login with another role": "Role specified doesn't exist or is not authorized",
    "Incorrect username or password was specified": "Incorrect username or password was specified",
    "This session does not have a current database": "Database specified not found",
    "Verify the account name is correct": "Can't find an account with the specified account ID",
}


@SourceRegistry.register
class SnowflakeSource(SQLSource[SnowflakeSourceConfig]):
    @property
    def get_implementation(self) -> SnowflakeImplementation:
        return _SNOWFLAKE_IMPLEMENTATION

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
            # Raised from the shared `_evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. a narrower NUMBER widened
            # to a larger NUMBER/BIGINT) after the destination table was created with the
            # narrower type. Delta Lake can't widen an existing column in place, so retrying
            # won't help — the table must be reset and fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
        }

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

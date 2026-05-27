from typing import Optional, cast

from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.generated_configs import MSSQLSourceConfig
from posthog.temporal.data_imports.sources.mssql.mssql import MSSQLImplementation

from products.data_warehouse.backend.types import ExternalDataSourceType

MSSQLErrors = {
    "Login failed for user": "Login failed for database",
    "Adaptive Server is unavailable or does not exist": "Could not connect to SQL server - check server host and port",
    "connection timed out": "Could not connect to SQL server - check server firewall settings",
}

_MSSQL_IMPLEMENTATION = MSSQLImplementation()


@SourceRegistry.register
class MSSQLSource(SQLSource[MSSQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    @property
    def get_implementation(self) -> MSSQLImplementation:
        return _MSSQL_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MSSQL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Adaptive Server connection failed": None,
            "Login failed for user": None,
            "Cannot find the CREDENTIAL": "Cannot find the credential - check that it exists and you have permission to access it",
            # Raised from the shared `_decimal_array_from_values` fallback in
            # `pipelines/pipeline/utils.py` when a numeric/decimal/money value exceeds Delta
            # Lake's decimal budget (precision > 76 or scale > 32). Fixed source-data shape —
            # retrying won't help.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
            # Raised from the shared `_evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT` → `BIGINT`) after the
            # destination table was created with the narrower type. Delta Lake can't widen an
            # existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MSSQL,
            label="Microsoft SQL Server",
            caption="Enter your Microsoft SQL Server/Azure SQL Server credentials to automatically pull your SQL data into the PostHog Data warehouse.",
            iconPath="/static/services/sql-azure.png",
            docsUrl="https://posthog.com/docs/cdp/sources/azure-db",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="mssql://user:password@localhost:1433/database",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="localhost",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="1433",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="msdb",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="sa",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="dbo",
                        secret=False,
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
        )

    def validate_credentials(
        self, config: MSSQLSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        from pymssql import OperationalError

        is_ssh_valid, ssh_valid_errors = self.ssh_tunnel_is_valid(config, team_id)
        if not is_ssh_valid:
            return is_ssh_valid, ssh_valid_errors

        valid_host, host_errors = self.is_database_host_valid(
            config.host, team_id, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            return valid_host, host_errors

        try:
            self.get_schemas(config, team_id)
        except OperationalError as e:
            error_msg = " ".join(str(n) for n in e.args)
            for key, value in MSSQLErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to MS SQL. Please check all connection details are valid."
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or "Could not connect to MS SQL via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to MS SQL. Please check all connection details are valid."

        return True, None

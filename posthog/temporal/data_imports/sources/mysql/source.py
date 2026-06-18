from typing import TYPE_CHECKING, Optional, cast

from sshtunnel import BaseSSHTunnelForwarderError

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from posthog.temporal.data_imports.sources.mysql.mysql import (
    MySQLImplementation,
    get_connection_metadata as get_mysql_connection_metadata,
)

from products.data_warehouse.backend.mysql_helpers import reconcile_mysql_schemas
from products.data_warehouse.backend.types import ExternalDataSourceType

_MYSQL_IMPLEMENTATION = MySQLImplementation()


@SourceRegistry.register
class MySQLSource(SQLSource[MySQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    @property
    def get_implementation(self) -> MySQLImplementation:
        return _MYSQL_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MYSQL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MY_SQL,
            category=DataWarehouseSourceCategory.DATABASES,
            caption="Enter your MySQL/MariaDB credentials to automatically pull your MySQL data into the PostHog Data warehouse.",
            iconPath="/static/services/mysql.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mysql",
            fields=cast(
                list[FieldType],
                [
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
                        placeholder="3306",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mysql",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mysql",
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
                        required=False,
                        placeholder="Leave blank to include all databases",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="using_ssl",
                        label="Use SSL?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Can't connect to MySQL server on": None,
            "No primary key defined for table": None,
            # MySQL/MariaDB error 1045 (ER_ACCESS_DENIED_ERROR): the user/password (or the
            # user's host grant) is wrong. Surface it as an auth failure — mirroring the Postgres
            # source — so the user fixes credentials instead of the generic "check connection
            # details" message sending them to check the host/port.
            "Access denied for user": "Invalid user or password",
            "sqlstate 42S02": None,  # Table not found error
            "ProgrammingError: (1146": None,  # Table not found error
            "OperationalError: (1356": None,  # View not found error
            "Bad handshake": None,
            # MySQL/MariaDB error 1129 (ER_HOST_IS_BLOCKED): the server has blocked our import
            # host because aborted/interrupted connections from it exceeded `max_connect_errors`.
            # The block is server-side state that only a DB admin can clear (FLUSH HOSTS /
            # `mysqladmin flush-hosts`, a restart, or raising `max_connect_errors`) — retrying just
            # adds more failed connections and keeps the host blocked. Match only the stable phrase,
            # not the volatile host IP or the `mysqladmin`/`mariadb-admin` wording that varies by server.
            "is blocked because of many connection errors": "Your MySQL/MariaDB server has blocked PostHog's host after too many interrupted connections (error 1129). Ask your database admin to run 'FLUSH HOSTS' (or 'mysqladmin flush-hosts') and consider raising 'max_connect_errors', then retry the sync.",
            # OpenSSL's signature for "tried to speak TLS to an endpoint that replied with
            # non-TLS bytes" — the source has SSL enabled but the server (or a proxy in front
            # of it, e.g. a plain TCP proxy) doesn't speak TLS, or the host/port is wrong. This
            # arrives wrapped as a pymysql OperationalError(2013, 'Lost connection ...'), but it
            # is a deterministic config mismatch, not the transient connection-drop that 2013
            # usually signals — so match only the stable SSL token, never the generic 2013 text.
            "[SSL: WRONG_VERSION_NUMBER]": "We couldn't establish an SSL connection to your MySQL server — it responded as if SSL is not enabled. If your server (or a proxy in front of it) doesn't support SSL, set 'Use SSL?' to No; otherwise check that you're connecting to an SSL-enabled host and port.",
            # Raised from the shared `_decimal_array_from_values` fallback in
            # `pipelines/pipeline/utils.py` when a numeric/decimal value exceeds Delta Lake's
            # decimal budget (precision > 76 or scale > 32). Fixed source-data shape — retrying
            # won't help.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT` → `BIGINT`) after the
            # destination table was created with the narrower type. Delta Lake can't widen an
            # existing column in place, so retrying won't help — the table must be reset and
            # fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # MySQL/MariaDB error 1054 (ER_BAD_FIELD_ERROR): a column the sync query references no
            # longer exists in the source table — almost always the configured incremental field
            # after the column was renamed or dropped (schema drift). The streaming query reissues
            # the same WHERE/ORDER BY on every attempt, so it fails identically forever; the COUNT(*)
            # probe already swallows this same error expecting it to be classified here. Match on the
            # locale-independent error code (the column name and clause are volatile, and the message
            # text is translated on non-English servers) so it catches both the raw pymysql string and
            # the Temporal-wrapped `OperationalError: (1054, ...)` form.
            '(1054, "Unknown column': "A column referenced during sync no longer exists in your source table (MySQL error 1054). This usually means a column was renamed or dropped — if it's the table's incremental field, update it to a column that exists (or switch to a full re-sync), then resync.",
        }

    def reconcile_schema_metadata(
        self,
        source: "ExternalDataSource",
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Delegates to `reconcile_mysql_schemas` so direct-query mode also rebuilds DWH tables."""
        return reconcile_mysql_schemas(source=source, source_schemas=source_schemas, team_id=team_id)

    def get_connection_metadata(
        self, config: MySQLSourceConfig, team_id: int, require_ssl: bool = False
    ) -> dict[str, object]:
        # `require_ssl` keeps signature parity with Postgres; MySQL SSL is governed by
        # `config.using_ssl` inside `connect`.
        with self.get_implementation.connect(config) as conn:
            return get_mysql_connection_metadata(conn, database=config.database)

    def validate_credentials(
        self, config: MySQLSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
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
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or f"Could not connect to {self.get_source_config.name} via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            # Connection/credential failures we already classify as non-retryable during sync
            # (an unreachable host, a refused connection, a blocked host, an SSL mismatch, ...)
            # are expected user/upstream errors, not bugs on our side. Surface the friendly
            # message without reporting them to error tracking — only genuinely unexpected
            # failures get captured. Mirrors the Postgres and MSSQL `validate_credentials` handling.
            error_msg = " ".join(str(arg) for arg in e.args) if e.args else str(e)
            for pattern, friendly_error in self.get_non_retryable_errors().items():
                if pattern in error_msg:
                    return (
                        False,
                        friendly_error
                        or f"Could not connect to {self.get_source_config.name}. Please check all connection details are valid.",
                    )

            capture_exception(e)
            return (
                False,
                f"Could not connect to {self.get_source_config.name}. Please check all connection details are valid.",
            )

        return True, None

    def validate_credentials_for_access_method(
        self,
        config: MySQLSourceConfig,
        team_id: int,
        access_method: str,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        return self.validate_credentials(config, team_id, schema_name=schema_name)

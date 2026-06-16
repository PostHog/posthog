from typing import Optional, cast

from sshtunnel import BaseSSHTunnelForwarderError

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
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from posthog.temporal.data_imports.sources.mysql.mysql import MySQLImplementation

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
                        required=True,
                        placeholder="public",
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
            "Access denied for user": None,
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
            # Raised by the `sshtunnel` library from `open_ssh_tunnel` when the customer's SSH
            # bastion/gateway can't bring up a session — the gateway is unreachable, refusing
            # connections, or misconfigured. This is a deterministic config/connectivity problem
            # with the customer's own SSH host; retrying just re-fails until they fix it. The
            # global `Any_Source_Errors` already classes this string as non-retryable, but the
            # schema-discovery (`sync_new_schemas_activity`) and import paths only consult the
            # per-source list, so it must be listed here too.
            "Could not establish session to SSH gateway": "We couldn't open the SSH tunnel to your database — the SSH gateway didn't establish a session. Check that the SSH tunnel host, port, and credentials are correct and that the gateway is reachable and accepting connections.",
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
        }

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
            capture_exception(e)
            return (
                False,
                f"Could not connect to {self.get_source_config.name}. Please check all connection details are valid.",
            )

        return True, None

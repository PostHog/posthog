from typing import Optional, cast

import structlog
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
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
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.sql.base import DiscoveryResult, SQLSource
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from posthog.temporal.data_imports.sources.mysql.mysql import (
    filter_mysql_incremental_fields,
    get_primary_keys_for_schemas as get_mysql_primary_keys_for_schemas,
    get_schemas as get_mysql_schemas,
    mysql_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MySQLSource(SQLSource[MySQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    source_display_name = "MySQL"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MYSQL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MY_SQL,
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
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="3306",
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mysql",
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mysql",
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="public",
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
        }

    # ------------------------------------------------------------------
    # SQLSource hooks
    # ------------------------------------------------------------------

    def _discover(
        self,
        config: MySQLSourceConfig,
        names: list[str] | None,
        with_counts: bool,
    ) -> DiscoveryResult:
        with self.with_ssh_tunnel(config) as (host, port):
            columns_by_table = get_mysql_schemas(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                using_ssl=config.using_ssl,
                schema=config.schema,
                names=names,
            )
            try:
                detected_pks = get_mysql_primary_keys_for_schemas(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    schema=config.schema,
                    table_names=list(columns_by_table.keys()),
                    using_ssl=config.using_ssl,
                )
            except Exception as e:
                structlog.get_logger().warning("Failed to detect primary keys for MySQL schemas", exc_info=e)
                detected_pks = dict.fromkeys(columns_by_table.keys())

        return DiscoveryResult(
            columns_by_table=columns_by_table,
            primary_keys_by_table=detected_pks,
        )

    def _filter_incremental_fields(self) -> IncrementalFieldFilter:
        return filter_mysql_incremental_fields

    def source_for_pipeline(self, config: MySQLSourceConfig, inputs: SourceInputs) -> SourceResponse:
        ssh_tunnel = self.make_ssh_tunnel_func(config)

        return mysql_source(
            tunnel=ssh_tunnel,
            user=config.user,
            password=config.password,
            database=config.database,
            using_ssl=config.using_ssl,
            schema=config.schema,
            table_names=[inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    # ------------------------------------------------------------------
    # Credentials validation — stays on the subclass because the
    # error-mapping shape is driver specific (common work to land in a
    # follow-up once more drivers are on SQLSource).
    # ------------------------------------------------------------------

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
                or f"Could not connect to {self.source_display_name} via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return (
                False,
                f"Could not connect to {self.source_display_name}. Please check all connection details are valid.",
            )

        return True, None

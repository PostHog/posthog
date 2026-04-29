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
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from posthog.temporal.data_imports.sources.mysql.mysql import (
    filter_mysql_incremental_fields,
    get_primary_keys_for_schemas as get_mysql_primary_keys_for_schemas,
    get_schemas as get_mysql_schemas,
    mysql_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField


@SourceRegistry.register
class MySQLSource(SimpleSource[MySQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
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
            # Raised from the shared `_decimal_array_from_values` fallback in
            # `pipelines/pipeline/utils.py` when a numeric/decimal value exceeds Delta Lake's
            # decimal budget (precision > 76 or scale > 32). Fixed source-data shape — retrying
            # won't help.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
        }

    def get_schemas(
        self, config: MySQLSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = []

        with self.with_ssh_tunnel(config) as (host, port):
            db_schemas = get_mysql_schemas(
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
                    table_names=list(db_schemas.keys()),
                    using_ssl=config.using_ssl,
                )
            except Exception as e:
                structlog.get_logger().warning("Failed to detect primary keys for MySQL schemas", exc_info=e)
                detected_pks = {}

        for table_name, columns in db_schemas.items():
            incremental_field_tuples = filter_mysql_incremental_fields(columns)
            incremental_fields: list[IncrementalField] = [
                {
                    "label": field_name,
                    "type": field_type,
                    "field": field_name,
                    "field_type": field_type,
                    "nullable": nullable,
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
                    detected_primary_keys=detected_pks.get(table_name)
                    or (["id"] if any(col[0] == "id" for col in columns) else None),
                )
            )

        return schemas

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
                or "Could not connect to MySQL via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to MySQL. Please check all connection details are valid."

        return True, None

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

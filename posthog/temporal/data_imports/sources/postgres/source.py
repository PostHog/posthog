from typing import cast

from psycopg import OperationalError
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from posthog.temporal.data_imports.sources.postgres.postgres import (
    filter_postgres_incremental_fields,
    get_postgres_row_count,
    get_schemas as get_postgres_schemas,
    postgres_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField

PostgresErrors = {
    "password authentication failed for user": "Invalid user or password",
    "could not translate host name": "Could not connect to the host",
    "Is the server running on that host and accepting TCP/IP connections": "Could not connect to the host on the port given",
    'database "': "Database does not exist",
    "timeout expired": "Connection timed out. Does your database have our IP addresses allowed?",
}


@SourceRegistry.register
class PostgresSource(SimpleSource[PostgresSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    def __init__(self, source_name: str = "Postgres"):
        super().__init__()
        self.source_name = source_name

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTGRES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POSTGRES,
            caption="Enter your Postgres credentials to automatically pull your Postgres data into the PostHog Data warehouse",
            iconPath="/static/services/postgres.png",
            docsUrl="https://posthog.com/docs/cdp/sources/postgres",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="postgresql://user:password@localhost:5432/database",
                    ),
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
                        placeholder="5432",
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="postgres",
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="postgres",
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
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
            featured=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "NoSuchTableError": None,
            "is not permitted to log in": None,
            "Tenant or user not found connection to server": None,
            "FATAL: Tenant or user not found": None,
            "error received from server in SCRAM exchange: Wrong password": None,
            "could not translate host name": None,
            "timeout expired connection to server at": None,
            "password authentication failed for user": None,
            "No primary key defined for table": None,
            "failed: timeout expired": None,
            "SSL connection has been closed unexpectedly": None,
            "Address not in tenant allow_list": None,
            "FATAL: no such database": None,
            "does not exist": None,
            "timestamp too small": None,
            "QueryTimeoutException": None,
            "TemporaryFileSizeExceedsLimitException": None,
            "Name or service not known": None,
            "Network is unreachable": None,
            "InsufficientPrivilege": None,
            "OperationalError: connection failed: connection to server at": None,
            "password authentication failed connection": None,
            "connection timeout expired": None,
        }

    def get_schemas(self, config: PostgresSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas = []

        with self.with_ssh_tunnel(config) as (host, port):
            db_schemas = get_postgres_schemas(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                schema=config.schema,
            )

            if with_counts:
                row_counts = get_postgres_row_count(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    schema=config.schema,
                )
            else:
                row_counts = {}

        for table_name, columns in db_schemas.items():
            column_info = [(col_name, col_type) for col_name, col_type in columns]

            incremental_field_tuples = filter_postgres_incremental_fields(column_info)
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
                    row_count=row_counts.get(table_name, None),
                )
            )

        return schemas

    def validate_credentials(self, config: PostgresSourceConfig, team_id: int) -> tuple[bool, str | None]:
        is_ssh_valid, ssh_valid_errors = self.ssh_tunnel_is_valid(config)
        if not is_ssh_valid:
            return is_ssh_valid, ssh_valid_errors

        valid_host, host_errors = self.is_database_host_valid(
            config.host, team_id, config.ssh_tunnel.enabled if config.ssh_tunnel else False
        )
        if not valid_host:
            return valid_host, host_errors

        try:
            self.get_schemas(config, team_id)
        except OperationalError as e:
            error_msg = " ".join(str(n) for n in e.args)
            for key, value in PostgresErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, f"Could not connect to {self.source_name}. Please check all connection details are valid."
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or f"Could not connect to {self.source_name} via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return False, f"Could not connect to {self.source_name}. Please check all connection details are valid."

        return True, None

    def source_for_pipeline(self, config: PostgresSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

        ssh_tunnel = self.make_ssh_tunnel_func(config)

        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)

        return postgres_source(
            tunnel=ssh_tunnel,
            user=config.user,
            password=config.password,
            database=config.database,
            sslmode="prefer",
            schema=config.schema,
            table_names=[inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            chunk_size_override=schema.chunk_size_override,
            team_id=inputs.team_id,
        )

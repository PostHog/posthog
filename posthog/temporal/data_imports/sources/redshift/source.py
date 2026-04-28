from typing import Optional, cast

import structlog
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
from posthog.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig
from posthog.temporal.data_imports.sources.redshift.redshift import (
    filter_redshift_incremental_fields,
    get_primary_keys_for_schemas as get_redshift_primary_keys_for_schemas,
    get_redshift_row_count,
    get_schemas as get_redshift_schemas,
    redshift_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField

RedshiftErrors = {
    "password authentication failed for user": "Invalid user or password",
    "could not translate host name": "Could not connect to the host",
    "Is the server running on that host and accepting TCP/IP connections": "Could not connect to the host on the port given",
    'database "': "Database does not exist",
    "timeout expired": "Connection timed out. Does your database have our IP addresses allowed?",
    "SSL connection has been closed unexpectedly": "SSL connection error. Please check your SSL settings.",
    "Connection refused": "Connection refused. Please check the host and port.",
}


@SourceRegistry.register
class RedshiftSource(SimpleSource[RedshiftSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    def __init__(self, source_name: str = "Redshift"):
        super().__init__()
        self.source_name = source_name

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDSHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REDSHIFT,
            caption="Enter your Redshift credentials to automatically pull your Redshift data into the PostHog Data warehouse",
            iconPath="/static/services/redshift.png",
            docsUrl="https://posthog.com/docs/cdp/sources/redshift",
            releaseStatus="beta",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="redshift://user:password@my-cluster.abc123xyz.us-east-1.redshift.amazonaws.com:5439/dev",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-cluster.abc123xyz.us-east-1.redshift.amazonaws.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="5439",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="dev",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="awsuser",
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
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "NoSuchTableError": None,
            "is not permitted to log in": None,
            "could not translate host name": None,
            "timeout expired connection to server at": None,
            "password authentication failed for user": None,
            "No primary key defined for table": None,
            "failed: timeout expired": None,
            "SSL connection has been closed unexpectedly": None,
            "does not exist": None,
            "QueryTimeoutException": None,
            "TemporaryFileSizeExceedsLimitException": None,
            "Name or service not known": None,
            "Network is unreachable": None,
            "InsufficientPrivilege": None,
            "No route to host": None,
            "password authentication failed connection": None,
            "connection timeout expired": None,
            "Connection refused": None,
        }

    def get_schemas(
        self, config: RedshiftSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = []

        with self.with_ssh_tunnel(config) as (host, port):
            db_schemas = get_redshift_schemas(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                schema=config.schema,
                names=names,
            )
            try:
                detected_pks = get_redshift_primary_keys_for_schemas(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    schema=config.schema,
                    table_names=list(db_schemas.keys()),
                )
            except Exception as e:
                structlog.get_logger().warning("Failed to detect primary keys for Redshift schemas", exc_info=e)
                detected_pks = {}

            if with_counts:
                row_counts = get_redshift_row_count(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    schema=config.schema,
                    names=names,
                )
            else:
                row_counts = {}

        for table_name, columns in db_schemas.items():
            incremental_field_tuples = filter_redshift_incremental_fields(columns)
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
                    row_count=row_counts.get(table_name, None),
                    columns=columns,
                    detected_primary_keys=detected_pks.get(table_name)
                    or (["id"] if any(col[0] == "id" for col in columns) else None),
                )
            )

        return schemas

    def validate_credentials(
        self, config: RedshiftSourceConfig, team_id: int, schema_name: Optional[str] = None
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
        except OperationalError as e:
            error_msg = " ".join(str(n) for n in e.args)
            for key, value in RedshiftErrors.items():
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

    def source_for_pipeline(self, config: RedshiftSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

        ssh_tunnel = self.make_ssh_tunnel_func(config)

        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)

        return redshift_source(
            tunnel=ssh_tunnel,
            user=config.user,
            password=config.password,
            database=config.database,
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

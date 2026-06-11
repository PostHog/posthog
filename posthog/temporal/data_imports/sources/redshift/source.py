from typing import Optional, cast

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
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig
from posthog.temporal.data_imports.sources.redshift.redshift import RedshiftImplementation

from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

_REDSHIFT_IMPLEMENTATION = RedshiftImplementation()

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
class RedshiftSource(SQLSource[RedshiftSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    def __init__(self, source_name: str = "Redshift"):
        super().__init__()
        self.source_name = source_name

    @property
    def get_implementation(self) -> RedshiftImplementation:
        return _REDSHIFT_IMPLEMENTATION

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
            **self.default_non_retryable_errors(),
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
        # Resolve `chunk_size_override` (stored on
        # `ExternalDataSchema.sync_type_config`) here so the driver
        # implementation in `redshift.py` stays free of Django ORM
        # imports.
        schema_row = ExternalDataSchema.objects.get(id=inputs.schema_id)
        return self.get_implementation.build_pipeline(
            config, inputs, chunk_size_override=schema_row.chunk_size_override
        )

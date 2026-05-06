import logging
from typing import TYPE_CHECKING, Optional, cast

import structlog
from psycopg import OperationalError
from sshtunnel import BaseSSHTunnelForwarderError

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSource

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
from posthog.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig
from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import cdc_pg_connection, drop_slot_and_publication
from posthog.temporal.data_imports.sources.postgres.postgres import (
    SSLRequiredError,
    filter_postgres_incremental_fields,
    get_connection_metadata as get_postgres_connection_metadata,
    get_foreign_keys as get_postgres_foreign_keys,
    get_leading_index_columns,
    get_postgres_row_count,
    get_primary_key_columns,
    get_schemas as get_postgres_schemas,
    pg_connection,
    postgres_source,
    source_requires_ssl,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField

log = logging.getLogger(__name__)

PostgresErrors = {
    "password authentication failed for user": "Invalid user or password",
    "could not translate host name": "Could not connect to the host",
    "Is the server running on that host and accepting TCP/IP connections": "Could not connect to the host on the port given",
    'database "': "Database does not exist",
    "timeout expired": "Connection timed out. Does your database have our IP addresses allowed?",
    "SSL/TLS connection is required": "SSL/TLS connection is required but your database does not support it. Please enable SSL/TLS on your PostgreSQL server.",
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
                        placeholder="5432",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="postgres",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="postgres",
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
                        placeholder="public",
                        caption=(
                            "Required for warehouse imports. Leave blank only for direct Postgres queries "
                            "to browse tables across all non-system schemas."
                        ),
                        secret=False,
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
            "Connection refused": None,
            "No route to host": None,
            "password authentication failed connection": None,
            "connection timeout expired": None,
            "SSLRequiredError": None,
            "SSL/TLS connection is required": None,
            "DiskFull": "Source database ran out of disk space. Free up disk space on your database server or add an index on your incremental field to reduce temp file usage.",
            "No space left on device": "Source database ran out of disk space. Free up disk space on your database server or add an index on your incremental field to reduce temp file usage.",
            # Raised when a Postgres numeric value cannot be represented in any Delta-compatible
            # decimal type — the pipeline falls back through the best-fit decimal and
            # `decimal256(76, 32)` before giving up. Only triggers when source data genuinely
            # exceeds Delta Lake's decimal budget (precision > 76 or scale > 32); retrying won't
            # help because the value shape is fixed in the source.
            "Cannot build decimal array from values": "One of your numeric columns contains values that exceed our decimal storage limits (max precision 76, max scale 32). Please constrain the column with a lower precision/scale, cast it to text in a view, or round the values at the source.",
        }

    def cleanup_cdc_resources_on_deletion(self, source: "ExternalDataSource") -> None:
        """Drop the Temporal schedule + PostHog-managed slot/publication.

        Schedule lives on our side, slot lives on the customer's DB. No-op for
        postgres sources without CDC enabled.
        """
        cdc_config = PostgresCDCConfig.from_source(source)
        if not cdc_config.enabled:
            return

        # Lazy: data_load.service pulls in Temporal client / Celery setup we don't want at module load.
        from products.data_warehouse.backend.data_load.service import delete_cdc_extraction_schedule

        # Schedule key = source id. NotFound is a no-op.
        try:
            delete_cdc_extraction_schedule(str(source.id))
        except Exception:
            log.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(source.id)})

        if cdc_config.management_mode != "posthog":
            return
        if not cdc_config.slot_name or not cdc_config.publication_name:
            return

        try:
            with cdc_pg_connection(source, connect_timeout=10) as conn:
                drop_slot_and_publication(conn, cdc_config.slot_name, cdc_config.publication_name)
        except Exception:
            log.exception(
                "Failed to drop CDC slot/publication on source DB (best-effort)",
                extra={"source_id": str(source.id), "slot_name": cdc_config.slot_name},
            )

    def get_schemas(
        self, config: PostgresSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = []

        with self.with_ssh_tunnel(config) as (host, port):
            db_schemas = get_postgres_schemas(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                schema=config.schema,
                names=names,
            )
            db_foreign_keys = get_postgres_foreign_keys(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                schema=config.schema,
                names=names,
            )

            if with_counts:
                row_counts = get_postgres_row_count(
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

            table_names_by_schema: dict[str, list[str]] = {}
            table_names_by_source_location: dict[tuple[str, str], str] = {}
            for discovered_schema in db_schemas.values():
                table_names_by_schema.setdefault(discovered_schema.source_schema, []).append(
                    discovered_schema.source_table_name
                )
            for table_name, discovered_schema in db_schemas.items():
                table_names_by_source_location[
                    (discovered_schema.source_schema, discovered_schema.source_table_name)
                ] = table_name

            pk_columns_by_table: dict[str, list[str]] = {}
            # `indexed_columns_by_table` is None when discovery failed (so we default
            # `is_indexed=True` and never warn), and a dict[table -> set] when it
            # succeeded. A successful lookup returns an empty set for tables without
            # indexes — that's how we tell "no indexes" apart from "couldn't check".
            indexed_columns_by_table: dict[str, set[str]] | None = {}
            tables_with_pks: set[str] = set()

            try:
                with pg_connection(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                ) as conn:
                    # PK lookup powers `supports_cdc`. Wrap in try/except so a permissions
                    # quirk on `pg_catalog` (rare) only disables CDC advertising for this
                    # listing instead of breaking schema discovery for everyone — including
                    # non-CDC users.
                    try:
                        for source_schema, source_table_names in table_names_by_schema.items():
                            if not source_table_names:
                                continue
                            source_pk_columns_by_table = get_primary_key_columns(
                                conn, source_schema, source_table_names
                            )
                            for source_table_name, pk_columns in source_pk_columns_by_table.items():
                                display_name = table_names_by_source_location.get((source_schema, source_table_name))
                                if display_name is not None:
                                    pk_columns_by_table[display_name] = pk_columns
                        tables_with_pks = set(pk_columns_by_table.keys())
                    except Exception as e:
                        capture_exception(e)
                        pk_columns_by_table = {}
                        tables_with_pks = set()

                    # Index lookup powers the unindexed-incremental-field warning. Isolated
                    # in its own try/except so a failure here doesn't discard PK results
                    # (and vice versa). The helper catches and logs its own per-query errors
                    # and returns None on failure; once any schema returns None we mark the
                    # whole listing as unknown so the UI defaults to no warning rather than
                    # a misleading one.
                    try:
                        for source_schema, source_table_names in table_names_by_schema.items():
                            if not source_table_names:
                                continue
                            source_indexed_by_table = get_leading_index_columns(conn, source_schema, source_table_names)
                            if source_indexed_by_table is None:
                                indexed_columns_by_table = None
                                break
                            if indexed_columns_by_table is None:
                                continue
                            for source_table_name in source_table_names:
                                display_name = table_names_by_source_location.get((source_schema, source_table_name))
                                if display_name is not None:
                                    # Use an empty set when the table has no indexes, so the
                                    # frontend warning fires for those tables.
                                    indexed_columns_by_table[display_name] = source_indexed_by_table.get(
                                        source_table_name, set()
                                    )
                    except Exception as e:
                        structlog.get_logger().warning(
                            "Failed to detect leading index columns for Postgres schemas", exc_info=e
                        )
                        indexed_columns_by_table = None
            except Exception as e:
                # Connection-level failure: neither lookup is usable.
                capture_exception(e)
                pk_columns_by_table = {}
                indexed_columns_by_table = None
                tables_with_pks = set()

        for table_name, discovered_schema in db_schemas.items():
            incremental_field_tuples = filter_postgres_incremental_fields(discovered_schema.columns)
            # None when index discovery failed for the whole listing — default to True so
            # a transient permission/query error never produces a misleading warning.
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
                    supports_cdc=table_name in tables_with_pks,
                    incremental_fields=incremental_fields,
                    row_count=row_counts.get(table_name, None),
                    columns=discovered_schema.columns,
                    foreign_keys=db_foreign_keys.get(table_name, []),
                    source_catalog=discovered_schema.source_catalog,
                    source_schema=discovered_schema.source_schema,
                    source_table_name=discovered_schema.source_table_name,
                    detected_primary_keys=pk_columns_by_table.get(table_name)
                    or (["id"] if any(col[0] == "id" for col in discovered_schema.columns) else None),
                )
            )

        return schemas

    def validate_credentials(
        self, config: PostgresSourceConfig, team_id: int, schema_name: Optional[str] = None
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
            self.get_schemas(config, team_id, names=[schema_name] if schema_name else None)
        except SSLRequiredError as e:
            return False, str(e)
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

    def validate_credentials_for_access_method(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        access_method: str,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        if access_method != "direct":
            schema = config.schema.strip() if isinstance(config.schema, str) else ""
            if not schema and not schema_name:
                return False, "Schema is required for warehouse imports."

        return self.validate_credentials(config, team_id, schema_name=schema_name)

    def get_connection_metadata(
        self, config: PostgresSourceConfig, team_id: int, require_ssl: bool = False
    ) -> dict[str, object]:
        with self.with_ssh_tunnel(config) as (host, port):
            return get_postgres_connection_metadata(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                require_ssl=require_ssl,
            )

    def check_cdc_prerequisites(
        self,
        config: PostgresSourceConfig,
        management_mode: str,
        tables: list[str],
        slot_name: str | None = None,
        publication_name: str | None = None,
        require_ssl: bool = True,
    ) -> list[str]:
        """Validate Postgres CDC prerequisites against a live connection.

        Pre-creation check — no ExternalDataSource exists yet, so caller passes raw config.
        Defaults require_ssl=True (all new sources are past the SSL cutoff).
        """
        from posthog.temporal.data_imports.sources.postgres.cdc.prerequisite_validator import validate_cdc_prerequisites
        from posthog.temporal.data_imports.sources.postgres.postgres import _connect_to_postgres

        with self.with_ssh_tunnel(config) as (host, port):
            conn = _connect_to_postgres(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                require_ssl=require_ssl,
            )
            try:
                schema = config.schema.strip() if isinstance(config.schema, str) and config.schema.strip() else "public"
                return validate_cdc_prerequisites(
                    conn=conn,
                    management_mode=management_mode,  # type: ignore[arg-type]
                    tables=tables,
                    schema=schema,
                    slot_name=slot_name,
                    publication_name=publication_name,
                )
            finally:
                conn.close()

    def source_for_pipeline(self, config: PostgresSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from posthog.temporal.data_imports.sources.postgres.exceptions import CDCHandledExternally

        from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

        ssh_tunnel = self.make_ssh_tunnel_func(config)

        schema = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)
        schema_metadata = schema.schema_metadata or {}
        source_schema = (
            schema_metadata.get("source_schema") if isinstance(schema_metadata.get("source_schema"), str) else None
        )
        source_table_name = (
            schema_metadata.get("source_table_name")
            if isinstance(schema_metadata.get("source_table_name"), str)
            else None
        )

        # CDC streaming schemas are handled by CDCExtractionWorkflow, not here
        if schema.is_cdc and schema.cdc_mode == "streaming":
            raise CDCHandledExternally(
                f"Schema {schema.name} is in CDC streaming mode — handled by CDCExtractionWorkflow"
            )

        # CDC snapshot schemas fall through to run initial full_refresh via postgres_source()
        require_ssl = source_requires_ssl(schema.source, config)

        return postgres_source(
            tunnel=ssh_tunnel,
            user=config.user,
            password=config.password,
            database=config.database,
            sslmode="prefer",
            # config.schema wins so warehouse-mode renames flow through without rewriting
            # schema_metadata. Falls back to source_schema for direct mode (browse-all).
            schema=config.schema or source_schema or "public",
            table_names=[source_table_name or inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            chunk_size_override=schema.chunk_size_override,
            team_id=inputs.team_id,
            require_ssl=require_ssl,
            is_initial_sync=not schema.initial_sync_complete,
        )

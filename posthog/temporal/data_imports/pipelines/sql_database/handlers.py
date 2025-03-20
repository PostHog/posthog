import structlog
from typing import Optional
from psycopg2 import OperationalError
from pymssql import OperationalError as MSSQLOperationalError
from sshtunnel import BaseSSHTunnelForwarderError

from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.models.external_data_schema import (
    get_sql_schemas_for_source_type,
    filter_postgres_incremental_fields,
    filter_mysql_incremental_fields,
    filter_mssql_incremental_fields,
    get_postgres_row_count,
)
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)


class SQLSourceHandler(SourceHandler):
    def __init__(self, request_data: dict, team_id: Optional[int] = None, validate_db_host=None, expose_error=None):
        super().__init__(request_data, team_id)
        self._validate_database_host = validate_db_host
        self._expose_error = expose_error
        self.source_type = request_data.get("source_type")

    def validate_credentials(self) -> tuple[bool, str | None]:
        # Importing pymssql requires mssql drivers to be installed locally - see posthog/warehouse/README.md
        host = self.request_data.get("host", None)
        port = self.request_data.get("port", None)
        database = self.request_data.get("database", None)
        user = self.request_data.get("user", None)
        password = self.request_data.get("password", None)
        schema = self.request_data.get("schema", None)

        ssh_tunnel_obj = self.request_data.get("ssh-tunnel", {})
        using_ssh_tunnel = ssh_tunnel_obj.get("enabled", False)
        ssh_tunnel_host = ssh_tunnel_obj.get("host", None)
        ssh_tunnel_port = ssh_tunnel_obj.get("port", None)
        ssh_tunnel_auth_type_obj = ssh_tunnel_obj.get("auth_type", {})
        ssh_tunnel_auth_type = ssh_tunnel_auth_type_obj.get("selection", None)
        ssh_tunnel_auth_type_username = ssh_tunnel_auth_type_obj.get("username", None)
        ssh_tunnel_auth_type_password = ssh_tunnel_auth_type_obj.get("password", None)
        ssh_tunnel_auth_type_passphrase = ssh_tunnel_auth_type_obj.get("passphrase", None)
        ssh_tunnel_auth_type_private_key = ssh_tunnel_auth_type_obj.get("private_key", None)

        if not host or not port or not database or not user or not password or not schema:
            return False, "Missing required parameters: host, port, database, user, password, schema"

        ssh_tunnel = SSHTunnel(
            enabled=using_ssh_tunnel,
            host=ssh_tunnel_host,
            port=ssh_tunnel_port,
            auth_type=ssh_tunnel_auth_type,
            username=ssh_tunnel_auth_type_username,
            password=ssh_tunnel_auth_type_password,
            passphrase=ssh_tunnel_auth_type_passphrase,
            private_key=ssh_tunnel_auth_type_private_key,
        )

        if using_ssh_tunnel:
            auth_valid, auth_error_message = ssh_tunnel.is_auth_valid()
            if not auth_valid:
                return False, (
                    auth_error_message if len(auth_error_message) > 0 else "Invalid SSH tunnel auth settings"
                )

            port_valid, port_error_message = ssh_tunnel.has_valid_port()
            if not port_valid:
                return False, (
                    port_error_message if len(port_error_message) > 0 else "Invalid SSH tunnel auth settings"
                )

        # Validate internal postgres
        if not self._validate_database_host(host, self.team_id, using_ssh_tunnel):
            return False, "Cannot use internal database"

        try:
            result = get_sql_schemas_for_source_type(
                self.source_type,
                host,
                port,
                database,
                user,
                password,
                schema,
                ssh_tunnel,
                self.request_data.get("use_ssl", True),
            )
            if len(result.keys()) == 0:
                return False, "Schema doesn't exist"

            # Store the result for later use
            self.sql_schemas_result = result
            self.ssh_tunnel = ssh_tunnel
            self.host = host
            self.port = port
            self.database = database
            self.user = user
            self.password = password
            self.schema = schema

            return True, None

        except OperationalError as e:
            exposed_error = self._expose_error(e)
            if exposed_error is None:
                capture_exception(e)
            return False, exposed_error or self._get_generic_sql_error()

        except MSSQLOperationalError as e:
            error_msg = " ".join(str(n) for n in e.args)
            exposed_error = self._expose_error(error_msg)
            if exposed_error is None:
                capture_exception(e)
            return False, exposed_error or self._get_generic_sql_error()

        except BaseSSHTunnelForwarderError as e:
            return False, e.value or self._get_generic_sql_error()

        except Exception as e:
            capture_exception(e)
            logger.exception("Could not fetch schemas", exc_info=e)
            return False, self._get_generic_sql_error()

    def _get_generic_sql_error(self) -> str:
        if self.source_type == ExternalDataSource.Type.MYSQL:
            name = "MySQL"
        elif self.source_type == ExternalDataSource.Type.MSSQL:
            name = "SQL database"
        else:
            name = "Postgres"

        return f"Could not connect to {name}. Please check all connection details are valid."


class PostgresSourceHandler(SQLSourceHandler):
    def get_schema_options(self) -> list[dict]:
        filtered_results = [
            (table_name, filter_postgres_incremental_fields(columns))
            for table_name, columns in self.sql_schemas_result.items()
        ]

        rows = {}
        try:
            rows = get_postgres_row_count(
                self.host, self.port, self.database, self.user, self.password, self.schema, self.ssh_tunnel
            )
        except:
            pass

        return [
            {
                "table": table_name,
                "should_sync": False,
                "rows": rows.get(table_name, None),
                "incremental_fields": [
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in columns
                ],
                "incremental_available": True,
                "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                "sync_type": None,
            }
            for table_name, columns in filtered_results
        ]


class MySQLSourceHandler(SQLSourceHandler):
    def get_schema_options(self) -> list[dict]:
        filtered_results = [
            (table_name, filter_mysql_incremental_fields(columns))
            for table_name, columns in self.sql_schemas_result.items()
        ]

        return [
            {
                "table": table_name,
                "should_sync": False,
                "incremental_fields": [
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in columns
                ],
                "incremental_available": True,
                "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                "sync_type": None,
            }
            for table_name, columns in filtered_results
        ]


class MSSQLSourceHandler(SQLSourceHandler):
    def get_schema_options(self) -> list[dict]:
        filtered_results = [
            (table_name, filter_mssql_incremental_fields(columns))
            for table_name, columns in self.sql_schemas_result.items()
        ]

        return [
            {
                "table": table_name,
                "should_sync": False,
                "incremental_fields": [
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in columns
                ],
                "incremental_available": True,
                "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                "sync_type": None,
            }
            for table_name, columns in filtered_results
        ]

from typing import TYPE_CHECKING
from sshtunnel import BaseSSHTunnelForwarderError
from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.mysql.mysql import get_schemas as get_mysql_schemas, mysql_source
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from posthog.warehouse.sql_schemas import filter_mysql_incremental_fields
from posthog.warehouse.types import IncrementalField

if TYPE_CHECKING:
    from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class MySQLSource(BaseSource[MySQLSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> "ExternalDataSource.Type":
        from posthog.warehouse.models import ExternalDataSource

        return ExternalDataSource.Type.MYSQL

    def get_schemas(self, config: MySQLSourceConfig, team_id: int) -> list[SourceSchema]:
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
            )

        for table_name, columns in db_schemas.items():
            column_info = [(col_name, col_type) for col_name, col_type in columns]

            incremental_field_tuples = filter_mysql_incremental_fields(column_info)
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
                )
            )

        return schemas

    def validate_credentials(self, config: MySQLSourceConfig, team_id: int) -> tuple[bool, str | None]:
        is_ssh_valid, ssh_valid_errors = self.ssh_tunnel_is_valid(config)
        if not is_ssh_valid:
            return is_ssh_valid, ssh_valid_errors

        valid_host, host_errors = self.is_database_host_valid(config.host, team_id, config.ssh_tunnel.enabled)
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
        with self.with_ssh_tunnel(config) as (host, port):
            return mysql_source(
                host=host,
                port=port,
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

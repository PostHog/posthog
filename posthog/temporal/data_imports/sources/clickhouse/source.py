from typing import cast

from sshtunnel import BaseSSHTunnelForwarderError

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    Option,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSSHTunnelConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin, ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import ClickHouseSourceConfig
from posthog.temporal.data_imports.sources.clickhouse.clickhouse import (
    filter_clickhouse_incremental_fields,
    get_clickhouse_schemas,
    get_clickhouse_row_count,
    clickhouse_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField


@SourceRegistry.register
class ClickHouseSource(SimpleSource[ClickHouseSourceConfig], SSHTunnelMixin, ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLICKHOUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLICKHOUSE,
            caption="Enter your ClickHouse credentials to automatically pull your ClickHouse data into the PostHog Data warehouse",
            iconPath="/static/services/clickhouse.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clickhouse",
            feature_flag="dwh_clickhouse",
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
                        placeholder="8123",
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="default",
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="User",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="default",
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldSelectConfig(
                        name="secure",
                        label="Use SSL?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[Option(label="Yes", value="true"), Option(label="No", value="false")],
                    ),
                    SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="Use SSH tunnel?"),
                ],
            ),
        )

    def get_schemas(self, config: ClickHouseSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas = []

        with self.with_ssh_tunnel(config) as (host, port):
            db_schemas = get_clickhouse_schemas(
                host=host,
                port=port,
                user=config.user,
                password=config.password,
                database=config.database,
                secure=config.secure,
            )

            if with_counts:
                row_counts = get_clickhouse_row_count(
                    host=host,
                    port=port,
                    user=config.user,
                    password=config.password,
                    database=config.database,
                    secure=config.secure,
                )
            else:
                row_counts = {}

        for table_name, columns in db_schemas.items():
            column_info = [(col_name, col_type) for col_name, col_type in columns]

            incremental_field_tuples = filter_clickhouse_incremental_fields(column_info)
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

    def validate_credentials(self, config: ClickHouseSourceConfig, team_id: int) -> tuple[bool, str | None]:
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
        except BaseSSHTunnelForwarderError as e:
            return (
                False,
                e.value
                or "Could not connect to ClickHouse via the SSH tunnel. Please check all connection details are valid.",
            )
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to ClickHouse. Please check all connection details are valid."

        return True, None

    def source_for_pipeline(self, config: ClickHouseSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

        ssh_tunnel = self.make_ssh_tunnel_func(config)

        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)

        return clickhouse_source(
            tunnel=ssh_tunnel,
            user=config.user,
            password=config.password,
            database=config.database,
            secure=config.secure,
            table_names=[inputs.schema_name],
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            chunk_size_override=schema.chunk_size_override,
            team_id=inputs.team_id,
        )

from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.mixins import SSHTunnelMixin
from posthog.temporal.data_imports.pipelines.postgres.postgres import (
    postgres_source,
    get_schemas as get_postgres_schemas,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources import PostgresSourceConfig
from posthog.warehouse.models import ExternalDataSource
from posthog.warehouse.models.external_data_schema import filter_postgres_incremental_fields
from posthog.warehouse.types import IncrementalField


@SourceRegistry.register
class PostgresSource(BaseSource[PostgresSourceConfig], SSHTunnelMixin):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.POSTGRES

    def get_schemas(self, config: PostgresSourceConfig) -> list[SourceSchema]:
        schemas = []

        # TODO: refactor get_postgres_schemas to not explictly set up ssh tunnel
        db_schemas = get_postgres_schemas(config)

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
                )
            )

        return schemas

    def source_for_pipeline(self, config: PostgresSourceConfig, inputs: SourceInputs) -> SourceResponse:
        with self.with_ssh_tunnel(config) as (host, port):
            return postgres_source(
                host=host,
                port=port,
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
                team_id=inputs.team_id,
            )

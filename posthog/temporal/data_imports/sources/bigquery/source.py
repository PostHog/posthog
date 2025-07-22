from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.bigquery import (
    validate_credentials as validate_bigquery_credentials,
    get_schemas as get_bigquery_schemas,
    filter_incremental_fields as filter_bigquery_incremental_fields,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class BigQuerySource(BaseSource[BigQuerySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.BIGQUERY

    def get_schemas(self, config: BigQuerySourceConfig) -> list[SourceSchema]:
        # TODO: convert pipeline/bigquery to use new config
        bq_schemas = get_bigquery_schemas(
            config,
            logger=None,
        )

        filtered_results = [
            (table_name, filter_bigquery_incremental_fields(columns)) for table_name, columns in bq_schemas.items()
        ]

        return [
            SourceSchema(
                name=table_name,
                supports_incremental=len(columns) > 0,
                supports_append=len(columns) > 0,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in columns
                ],
            )
            for table_name, columns in filtered_results
        ]

    def validate_credentials(self, config: BigQuerySourceConfig) -> tuple[bool, str | None]:
        if validate_bigquery_credentials(
            config.dataset_id,
            {
                "project_id": config.key_file.project_id,
                "private_key": config.key_file.private_key,
                "private_key_id": config.key_file.private_key_id,
                "client_email": config.key_file.client_email,
                "token_uri": config.key_file.token_uri,
            },
            config.dataset_project.dataset_project_id if config.dataset_project else None,
        ):
            return True, None

        return False, "Invalid BigQuery credentials"

    def source_for_pipeline(self, config: BigQuerySourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Vitally source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)

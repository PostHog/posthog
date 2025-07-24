from datetime import datetime
from typing import cast
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldFileUploadConfig,
    SourceFieldSwitchGroupConfig,
    Type4,
    SourceFieldFileUploadJsonFormatConfig,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.bigquery.bigquery import (
    delete_all_temp_destination_tables,
    delete_table,
    validate_credentials as validate_bigquery_credentials,
    get_schemas as get_bigquery_schemas,
    filter_incremental_fields as filter_bigquery_incremental_fields,
    bigquery_source,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class BigQuerySource(BaseSource[BigQuerySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.BIGQUERY

    def get_schemas(self, config: BigQuerySourceConfig, team_id: int) -> list[SourceSchema]:
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

    def validate_credentials(self, config: BigQuerySourceConfig, team_id: int) -> tuple[bool, str | None]:
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
        if not config.key_file.private_key:
            raise ValueError(f"Missing private key for BigQuery: '{inputs.job_id}'")

        using_temporary_dataset = False
        dataset_project_id: str | None = None

        if (
            config.dataset_project
            and config.dataset_project.enabled
            and config.dataset_project.dataset_project_id is not None
            and config.dataset_project.dataset_project_id != ""
        ):
            using_temporary_dataset = True
            dataset_project_id = config.dataset_project.dataset_project_id

        # Including the schema ID in table prefix ensures we only delete tables
        # from this schema, and that if we fail we will clean up any previous
        # execution's tables.
        # Table names in BigQuery can have up to 1024 bytes, so we can be pretty
        # relaxed with using a relatively long UUID as part of the prefix.
        # Some special characters do need to be replaced, so we use the hex
        # representation of the UUID.
        destination_table_prefix = f"__posthog_import_{inputs.schema_id}"

        destination_table_dataset_id = dataset_project_id if using_temporary_dataset else config.dataset_id
        destination_table = f"{config.key_file.project_id}.{destination_table_dataset_id}.{destination_table_prefix}{inputs.job_id}_{str(datetime.now().timestamp()).replace('.', '')}"

        delete_all_temp_destination_tables(
            dataset_id=config.dataset_id,
            table_prefix=destination_table_prefix,
            project_id=config.key_file.project_id,
            dataset_project_id=dataset_project_id,
            private_key=config.key_file.private_key,
            private_key_id=config.key_file.private_key_id,
            client_email=config.key_file.client_email,
            token_uri=config.key_file.token_uri,
            logger=inputs.logger,
        )

        try:
            return bigquery_source(
                dataset_id=config.dataset_id,
                project_id=config.key_file.project_id,
                dataset_project_id=dataset_project_id,
                private_key=config.key_file.private_key,
                private_key_id=config.key_file.private_key_id,
                client_email=config.key_file.client_email,
                token_uri=config.key_file.token_uri,
                table_name=inputs.schema_name,
                should_use_incremental_field=inputs.should_use_incremental_field,
                logger=inputs.logger,
                bq_destination_table_id=destination_table,
                incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
                incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        finally:
            # Delete the destination table (if it exists) after we're done with it
            delete_table(
                table_id=destination_table,
                project_id=config.key_file.project_id,
                private_key=config.key_file.private_key,
                private_key_id=config.key_file.private_key_id,
                client_email=config.key_file.client_email,
                token_uri=config.key_file.token_uri,
            )
            inputs.logger.info(f"Deleting bigquery temp destination table: {destination_table}")

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BIG_QUERY,
            caption="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Google Cloud JSON key file",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["project_id", "private_key", "private_key_id", "client_email", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="dataset_id", label="Dataset ID", type=Type4.TEXT, required=True, placeholder=""
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="temporary-dataset",
                        label="Use a different dataset for the temporary tables?",
                        caption="We have to create and delete temporary tables when querying your data, this is a requirement of querying large BigQuery tables. We can use a different dataset if you'd like to limit the permissions available to the service account provided.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="temporary_dataset_id",
                                    label="Dataset ID for temporary tables",
                                    type=Type4.TEXT,
                                    required=True,
                                    placeholder="",
                                )
                            ],
                        ),
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="dataset_project",
                        label="Use a different project for the dataset than your service account project?",
                        caption="If the dataset you're wanting to sync exists in a different project than that of your service account, use this to provide the project ID of the BigQuery dataset.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="dataset_project_id",
                                    label="Project ID for dataset",
                                    type=Type4.TEXT,
                                    required=True,
                                    placeholder="",
                                )
                            ],
                        ),
                    ),
                ],
            ),
        )

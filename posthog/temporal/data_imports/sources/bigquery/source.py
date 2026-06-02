from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)

from posthog.temporal.data_imports.sources.bigquery.bigquery import (
    BigQueryImplementation,
    build_destination_table_prefix,
    validate_bigquery_credentials,
)
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.sql.base import SQLSource
from posthog.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

__all__ = ["BigQuerySource", "build_destination_table_prefix"]

_BIGQUERY_IMPLEMENTATION = BigQueryImplementation()


@SourceRegistry.register
class BigQuerySource(SQLSource[BigQuerySourceConfig]):
    @property
    def get_implementation(self) -> BigQueryImplementation:
        return _BIGQUERY_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BIGQUERY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "PermissionDenied: 403 request failed": "BigQuery permission denied. Please check that your service account has the necessary permissions.",
            "NotFound: 404": "BigQuery dataset or table not found. Please verify your project, dataset, and table names.",
            # Raised from the shared `_evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT64` widened from a
            # narrower numeric type) after the destination table was created with the narrower
            # type. Delta Lake can't widen an existing column in place, so retrying won't help —
            # the table must be reset and fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
        }

    def validate_credentials(
        self, config: BigQuerySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        region: str | None = None
        if (
            config.use_custom_region
            and config.use_custom_region.enabled
            and config.use_custom_region.region is not None
            and config.use_custom_region.region != ""
        ):
            region = config.use_custom_region.region
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
            region,
        ):
            return True, None

        return False, "Invalid BigQuery credentials"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BIG_QUERY,
            iconPath="/static/services/bigquery.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bigquery",
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
                    SourceFieldSwitchGroupConfig(
                        name="use_custom_region",
                        label="Manually specify your dataset region?",
                        caption="In most cases, BigQuery is able to automatically determine the region your dataset is located in. For the rare instances that BigQuery fails to do so, you can manually specify your dataset region here.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="region",
                                    label="Region",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="us-east1",
                                    secret=False,
                                ),
                            ],
                        ),
                    ),
                    SourceFieldInputConfig(
                        name="dataset_id",
                        label="Dataset ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
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
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="",
                                    secret=False,
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
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="",
                                    secret=False,
                                )
                            ],
                        ),
                    ),
                ],
            ),
        )

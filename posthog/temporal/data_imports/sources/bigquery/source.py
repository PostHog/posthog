from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)

from posthog.temporal.data_imports.sources.bigquery.bigquery import (
    BIGQUERY_TOKEN_RESPONSE_ERROR,
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
            # OAuth2 error code returned by Google's token endpoint when the service account grant
            # is rejected — a rotated/revoked private key ("Invalid JWT Signature") or a deleted
            # service account ("account not found"). Raised as a `RefreshError` while refreshing the
            # token, so it surfaces on every BigQuery call rather than at a single site. Retrying
            # can't recover invalid credentials; the user must upload a new key file. Matched on the
            # stable `invalid_grant` code rather than `RefreshError`, which can also wrap transient
            # token-endpoint failures that should stay retryable.
            "invalid_grant": "Your BigQuery service account credentials were rejected by Google. The key may have been rotated or revoked, or the service account deleted. Please upload a new Google Cloud JSON key file.",
            # BigQuery prefixes every IAM/permission failure with "Access Denied:" — e.g.
            # "Access Denied: Table <id>: Permission bigquery.tables.getData denied on table <id>
            # (or it may not exist).". The matched string above only covers the REST client's
            # "PermissionDenied: 403 request failed" wording; the Storage Read API raises a
            # google.api_core PermissionDenied whose `str()` is "403 Access Denied: ..." instead,
            # so it slips through and retries forever. These are config/permission problems on the
            # customer's service account — retrying can't resolve them; the user must grant the
            # missing permission (or the referenced table/dataset must exist).
            "Access Denied:": "BigQuery denied access to a table or dataset. Please ensure your service account has read access (the bigquery.tables.getData permission, e.g. the BigQuery Data Viewer role) on every dataset and table you're syncing, then reconnect the source.",
            # Federated/external BigQuery tables (e.g. a Cloud SQL connection) read through to the
            # underlying database. When that database's role lacks read access, BigQuery surfaces the
            # upstream ACL failure inside a 400 BadRequest, e.g. "Error while reading data ...
            # Failed to fetch row from PostgreSQL server. Error: ERROR:  permission denied for table
            # <name>". This is a deterministic permission problem on the customer's data source —
            # retrying can't resolve it; the user must grant the federation's database user read
            # access. The "Access Denied:"/403 keys above only cover BigQuery's own IAM wording, so
            # this lowercase upstream form slips through and retries forever.
            "permission denied for table": 'BigQuery couldn\'t read a federated table because the underlying database denied permission ("permission denied for table"). Please grant the database user behind your BigQuery connection read access to the table, then reconnect the source.',
            # Raised from schema discovery (`get_columns`) and query jobs when the configured
            # dataset/table doesn't exist in the location we query — the dataset was deleted or
            # renamed, or it lives in a different region than the one we run against. The google
            # exception stringifies as "404 Not found: Dataset ... was not found in location US",
            # so match the stable phrasing here. Retrying can't recover — the user must fix the
            # dataset or set the correct region.
            "was not found in location": "BigQuery couldn't find the configured dataset or table. It may have been deleted or renamed, or it may live in a different region — verify your dataset and table names, and set the dataset region in your source configuration if it isn't in the US.",
            # Raised by google-cloud-bigquery's `TableReference.from_string` when a table id has
            # more than the three `project.dataset.table` components. This happens when the
            # Dataset ID field is set to `project.dataset` instead of just `dataset` — we then
            # build `project.project.dataset.table` and the client rejects it. It's a deterministic
            # config error, so retrying never succeeds.
            "table_id must be a fully-qualified ID in standard SQL format": "Your BigQuery Dataset ID looks misconfigured — it should be just the dataset name (for example `analytics`), not `project.dataset`. Please update the Dataset ID in your source configuration.",
            # Forbidden 403 with `reason: billingNotEnabled` — the customer's Google Cloud project
            # has billing disabled (BigQuery sandbox mode), so any query job is rejected before it
            # runs. There's nothing we can do but stop retrying until they enable billing.
            "Billing has not been enabled for this project": "BigQuery billing is not enabled for your Google Cloud project. Enable billing in the Google Cloud console (https://console.cloud.google.com/billing), then resume this source.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT64` widened from a
            # narrower numeric type) after the destination table was created with the narrower
            # type. Delta Lake can't widen an existing column in place, so retrying won't help —
            # the table must be reset and fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # Raised from `BigQueryImplementation.get_columns` when the service-account OAuth
            # token endpoint returns a non-JSON-object 200 (bad `token_uri`, or an intercepting
            # proxy). Authentication can't succeed until the key file is fixed, so retrying just
            # hammers the endpoint and spams error tracking.
            BIGQUERY_TOKEN_RESPONSE_ERROR: "We couldn't authenticate with BigQuery — Google's OAuth token endpoint returned an unexpected response. Please re-upload your service account key file and verify its token_uri.",
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
            category=DataWarehouseSourceCategory.DATABASES,
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

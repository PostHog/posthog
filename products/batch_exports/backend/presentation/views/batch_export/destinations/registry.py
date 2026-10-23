from products.batch_exports.backend.facade.enums import BatchExportDestinationType

from . import azure_blob, bigquery, databricks, http, postgres, redshift, s3, snowflake, validation, workflows

DESTINATION_SERIALIZERS: dict[str, type[validation.DestinationValidationSerializer]] = {
    BatchExportDestinationType.AWS_S3: s3.AwsS3DestinationRequestSerializer,
    BatchExportDestinationType.S3_COMPATIBLE: s3.S3CompatibleDestinationRequestSerializer,
    BatchExportDestinationType.AZURE_BLOB: azure_blob.AzureBlobDestinationRequestSerializer,
    BatchExportDestinationType.BIGQUERY: bigquery.BigQueryDestinationRequestSerializer,
    BatchExportDestinationType.DATABRICKS: databricks.DatabricksDestinationRequestSerializer,
    BatchExportDestinationType.POSTGRES: postgres.PostgresDestinationRequestSerializer,
    BatchExportDestinationType.REDSHIFT: redshift.RedshiftDestinationRequestSerializer,
    BatchExportDestinationType.SNOWFLAKE: snowflake.SnowflakeDestinationRequestSerializer,
    BatchExportDestinationType.HTTP: http.HTTPDestinationSerializer,
    BatchExportDestinationType.WORKFLOWS: workflows.WorkflowsDestinationSerializer,
    BatchExportDestinationType.NOOP: validation.DestinationValidationSerializer,
    BatchExportDestinationType.FILE_DOWNLOAD: validation.DestinationValidationSerializer,
}

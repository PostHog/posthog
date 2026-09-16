import { awsS3Definition } from './awss3'
import { azureBlobDefinition } from './azureblob'
import { bigqueryDefinition } from './bigquery'
import { databricksDefinition } from './databricks'
import { httpDefinition } from './http'
import { postgresDefinition } from './postgres'
import { redshiftDefinition } from './redshift'
import { s3CompatibleDefinition } from './s3compatible'
import { snowflakeDefinition } from './snowflake'
import type { BatchExportServiceType, DestinationDefinition } from './types'

export const DESTINATIONS: Record<BatchExportServiceType, DestinationDefinition> = {
    AwsS3: awsS3Definition,
    S3Compatible: s3CompatibleDefinition,
    Postgres: postgresDefinition,
    Redshift: redshiftDefinition,
    Snowflake: snowflakeDefinition,
    BigQuery: bigqueryDefinition,
    HTTP: httpDefinition,
    Databricks: databricksDefinition,
    AzureBlob: azureBlobDefinition,
}

export type { DestinationDefinition, BatchExportServiceType } from './types'

import { Dayjs } from 'lib/dayjs'

import {
    BatchExportConfiguration,
    BatchExportServiceAwsS3,
    BatchExportServiceAzureBlob,
    BatchExportServiceBigQuery,
    BatchExportServiceDatabricks,
    BatchExportServiceHTTP,
    BatchExportServicePostgres,
    BatchExportServiceRedshift,
    BatchExportServiceS3,
    BatchExportServiceS3Compatible,
    BatchExportServiceSnowflake,
} from '~/types'

export type BatchExportContext = 'batch_export' | 'hog_function'

export type BatchExportConfigurationForm = Omit<
    BatchExportConfiguration,
    'id' | 'destination' | 'start_at' | 'end_at'
> &
    Partial<BatchExportServicePostgres['config']> &
    Partial<BatchExportServiceRedshift['config']> &
    Partial<BatchExportServiceBigQuery['config']> &
    Partial<BatchExportServiceS3['config']> &
    Partial<BatchExportServiceAwsS3['config']> &
    Partial<BatchExportServiceS3Compatible['config']> &
    Partial<BatchExportServiceSnowflake['config']> &
    Partial<BatchExportServiceDatabricks['config']> &
    Partial<BatchExportServiceHTTP['config']> &
    Partial<BatchExportServiceAzureBlob['config']> & {
        destination:
            | 'S3'
            | 'AwsS3'
            | 'S3Compatible'
            | 'Snowflake'
            | 'Postgres'
            | 'BigQuery'
            | 'Redshift'
            | 'Databricks'
            | 'HTTP'
            | 'AzureBlob'
        start_at: Dayjs | null
        end_at: Dayjs | null
    }

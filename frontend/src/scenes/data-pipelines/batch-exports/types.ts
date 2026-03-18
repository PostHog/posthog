import { Dayjs } from 'lib/dayjs'

import {
    BatchExportConfiguration,
    BatchExportServiceAzureBlob,
    BatchExportServiceBigQuery,
    BatchExportServiceDatabricks,
    BatchExportServiceHTTP,
    BatchExportServicePostgres,
    BatchExportServiceRedshift,
    BatchExportServiceS3,
    BatchExportServiceSnowflake,
} from '~/types'

export type BatchExportConfigurationForm = Omit<
    BatchExportConfiguration,
    'id' | 'destination' | 'start_at' | 'end_at'
> &
    Partial<BatchExportServicePostgres['config']> &
    Partial<BatchExportServiceRedshift['config']> &
    Partial<BatchExportServiceBigQuery['config']> &
    Partial<BatchExportServiceS3['config']> &
    Partial<BatchExportServiceSnowflake['config']> &
    Partial<BatchExportServiceDatabricks['config']> &
    Partial<BatchExportServiceHTTP['config']> &
    Partial<BatchExportServiceAzureBlob['config']> & {
        destination: 'S3' | 'Snowflake' | 'Postgres' | 'BigQuery' | 'Redshift' | 'Databricks' | 'HTTP' | 'AzureBlob'
        start_at: Dayjs | null
        end_at: Dayjs | null
        json_config_file?: File[] | null
    }

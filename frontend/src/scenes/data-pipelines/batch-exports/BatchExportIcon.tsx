import IconHTTP from '@posthog/brand/hoggies/png/coffee-run'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { BatchExportService } from '~/types'

import IconS3 from 'public/services/aws-s3.png'
import IconAzureBlob from 'public/services/azure-blob-storage.png'
import IconBigQuery from 'public/services/bigquery.png'
import IconDatabricks from 'public/services/databricks.png'
import IconPostgres from 'public/services/postgres.png'
import IconRedshift from 'public/services/redshift.png'
import IconS3Compatible from 'public/services/s3-compatible.png'
import IconSnowflake from 'public/services/snowflake.png'

export function getBatchExportDocsUrl(service: BatchExportService['type']): string {
    // AwsS3 and S3Compatible share the one S3 docs page.
    const slug = service === 'AwsS3' || service === 'S3Compatible' ? 's3' : service.toLowerCase()
    return `https://posthog.com/docs/cdp/batch-exports/${slug}`
}

export const BATCH_EXPORT_ICON_MAP: Record<BatchExportService['type'], string> = {
    AzureBlob: IconAzureBlob,
    BigQuery: IconBigQuery,
    Postgres: IconPostgres,
    Redshift: IconRedshift,
    AwsS3: IconS3,
    S3Compatible: IconS3Compatible,
    Snowflake: IconSnowflake,
    HTTP: IconHTTP,
    Databricks: IconDatabricks,
}

export function RenderBatchExportIcon({
    type,
    size = 'small',
}: {
    type: BatchExportService['type']
    size?: 'small' | 'medium'
}): JSX.Element {
    const icon = BATCH_EXPORT_ICON_MAP[type]

    const sizePx = size === 'small' ? 30 : 45

    return (
        <div className="flex gap-4 items-center">
            <Tooltip
                title={
                    <>
                        {type}
                        <br />
                        Click to view docs
                    </>
                }
            >
                <Link to={getBatchExportDocsUrl(type)}>
                    <img src={icon} alt={type} height={sizePx} width={sizePx} />
                </Link>
            </Tooltip>
        </div>
    )
}

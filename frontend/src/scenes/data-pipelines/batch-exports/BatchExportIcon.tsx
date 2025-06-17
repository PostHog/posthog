import { Link, Tooltip } from '@posthog/lemon-ui'
import IconHTTP from 'public/hedgehog/running-hog.png'
import IconS3 from 'public/services/aws-s3.png'
import IconBigQuery from 'public/services/bigquery.png'
import IconPostgres from 'public/services/postgres.png'
import IconRedshift from 'public/services/redshift.png'
import IconSnowflake from 'public/services/snowflake.png'

import { BatchExportService } from '~/types'

export function getBatchExportUrl(service: BatchExportService['type']): string {
    return `https://posthog.com/docs/cdp/batch-exports/${service.toLowerCase()}`
}

export const BATCH_EXPORT_ICON_MAP: Record<BatchExportService['type'], string> = {
    BigQuery: IconBigQuery,
    Postgres: IconPostgres,
    Redshift: IconRedshift,
    S3: IconS3,
    Snowflake: IconSnowflake,
    HTTP: IconHTTP,
}

export function RenderBatchExportIcon({
    type,
    size = 'small',
}: {
    type: BatchExportService['type']
    size?: 'small' | 'medium'
}): JSX.Element {
    const icon = BATCH_EXPORT_ICON_MAP[type]

    const sizePx = size === 'small' ? 30 : 60

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
                <Link to={getBatchExportUrl(type)}>
                    <img src={icon} alt={type} height={sizePx} width={sizePx} />
                </Link>
            </Tooltip>
        </div>
    )
}

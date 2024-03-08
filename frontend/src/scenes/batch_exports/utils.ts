import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, BatchExportConfiguration, BatchExportDestination, BatchExportRun } from '~/types'

export function intervalToFrequency(interval: BatchExportConfiguration['interval']): string {
    return {
        day: 'daily',
        hour: 'hourly',
        'every 5 minutes': 'every 5 minutes',
    }[interval]
}

export function isRunInProgress(run: BatchExportRun): boolean {
    return ['Running', 'Starting'].includes(run.status)
}

export function humanizeDestination(destination: BatchExportDestination): string {
    if (destination.type === 'S3') {
        return `s3://${destination.config.bucket_name}/${destination.config.prefix}`
    }

    if (destination.type === 'Snowflake') {
        return `snowflake:${destination.config.account}:${destination.config.database}:${destination.config.table_name}`
    }

    if (destination.type === 'Postgres') {
        return `postgresql://${destination.config.user}:***@${destination.config.host}:${destination.config.port}/${destination.config.database}`
    }

    if (destination.type === 'Redshift') {
        return `redshift://${destination.config.user}:***@${destination.config.host}:${destination.config.port}/${destination.config.database}`
    }

    if (destination.type === 'BigQuery') {
        return `bigquery:${destination.config.project_id}:${destination.config.dataset_id}:${destination.config.table_id}`
    }

    return 'Unknown'
}

export function showBatchExports(): boolean {
    const { user } = useValues(userLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    return hasAvailableFeature(AvailableFeature.DATA_PIPELINES) || user?.is_impersonated == true
}

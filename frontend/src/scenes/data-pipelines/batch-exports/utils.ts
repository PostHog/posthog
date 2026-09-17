import { dayjs } from 'lib/dayjs'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { BatchExportRun, BatchExportService } from '~/types'
import { BATCH_EXPORT_SERVICE_NAMES } from '~/types'

export const humanizeBatchExportName = (service: BatchExportService['type']): string => {
    switch (service) {
        case 'HTTP':
            return 'PostHog HTTP'
        case 'AzureBlob':
            return 'Azure Blob Storage'
        case 'AwsS3':
            return 'AWS S3'
        case 'S3Compatible':
            return 'S3-compatible'
        default:
            return service
    }
}

// TODO: move this to DestinationDefinition so all destination config is in a single place
export const humanizeBatchExportDescription = (service: BatchExportService['type']): string => {
    switch (service) {
        case 'AwsS3':
            return 'Batch export data to an AWS S3 bucket'
        case 'S3Compatible':
            return 'Batch export data to an S3-compatible destination'
        default:
            return `${humanizeBatchExportName(service)} batch export`
    }
}

export const normalizeBatchExportService = (service: string): BatchExportService['type'] => {
    return (
        BATCH_EXPORT_SERVICE_NAMES.find((s) => s.toLowerCase() === service.toLowerCase()) ??
        (service as BatchExportService['type'])
    )
}

export const formatHourString = (hour: number): string => {
    return dayjs().hour(hour).format('HH:00')
}

export const hourOptions = Array.from({ length: 24 }, (_, hour) => ({
    value: hour,
    label: formatHourString(hour),
}))

export const dayOptions = [
    { value: 0, label: 'Sunday' },
    { value: 1, label: 'Monday' },
    { value: 2, label: 'Tuesday' },
    { value: 3, label: 'Wednesday' },
    { value: 4, label: 'Thursday' },
    { value: 5, label: 'Friday' },
    { value: 6, label: 'Saturday' },
]

/** Run or backfill workflow status (same union on both types). */
export type BatchExportStatus = BatchExportRun['status']

/** Statuses a person can filter runs by, collapsing the Temporal states they don't distinguish. */
export type BatchExportRunStatusGroup = 'running' | 'completed' | 'failed' | 'cancelled'

// Typed as a full Record so a new status fails the build until someone puts it in a group.
const STATUS_TO_GROUP: Record<BatchExportStatus, BatchExportRunStatusGroup> = {
    Starting: 'running',
    Running: 'running',
    ContinuedAsNew: 'running',
    Completed: 'completed',
    Failed: 'failed',
    FailedRetryable: 'failed',
    FailedBilling: 'failed',
    Cancelled: 'cancelled',
    Terminated: 'cancelled',
    TimedOut: 'cancelled',
}

export const BATCH_EXPORT_RUN_STATUS_FILTER_OPTIONS: { value: BatchExportRunStatusGroup; label: string }[] = [
    { value: 'running', label: 'Running' },
    { value: 'completed', label: 'Completed' },
    { value: 'failed', label: 'Failed' },
    { value: 'cancelled', label: 'Cancelled' },
]

export function batchExportRunStatusesForGroups(groups: BatchExportRunStatusGroup[]): BatchExportStatus[] {
    const selected = new Set(groups)
    return (Object.keys(STATUS_TO_GROUP) as BatchExportStatus[]).filter((status) =>
        selected.has(STATUS_TO_GROUP[status])
    )
}

export function statusToLemonTagType(status: BatchExportStatus, options?: { recordsFailed?: number }): LemonTagType {
    if (status === 'Completed' && options?.recordsFailed != null && options.recordsFailed > 0) {
        return 'warning'
    }
    switch (status) {
        case 'Completed':
            return 'success'
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            return 'default'
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            return 'warning'
        case 'Failed':
        case 'FailedRetryable':
        case 'FailedBilling':
            return 'danger'
        default:
            return 'default'
    }
}

export function statusToProgressStrokeColor(status: BatchExportStatus): string {
    switch (status) {
        case 'Completed':
            return 'var(--success)'
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            return 'var(--brand-blue)'
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            return 'var(--warning)'
        case 'Failed':
        case 'FailedRetryable':
        case 'FailedBilling':
            return 'var(--danger)'
        default:
            return 'var(--color-border-primary)'
    }
}

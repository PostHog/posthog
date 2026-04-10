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
        default:
            return service
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
            return 'var(--danger)'
        default:
            return 'var(--color-border-primary)'
    }
}

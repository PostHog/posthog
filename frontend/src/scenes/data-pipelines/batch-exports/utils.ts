import { dayjs } from 'lib/dayjs'

import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService } from '~/types'

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

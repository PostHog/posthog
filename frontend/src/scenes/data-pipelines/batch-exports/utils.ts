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

// Convert interval_offset (seconds) to hour for daily exports
export const intervalOffsetToHour = (offset: number | null | undefined): number => {
    if (offset === null || offset === undefined) {
        return 0
    }
    return Math.floor(offset / 3600)
}

// Convert hour to interval_offset (seconds) for daily exports
export const hourToIntervalOffset = (hour: number): number => {
    return hour * 3600
}

// Convert interval_offset (seconds) to day and hour for weekly exports
export const intervalOffsetToDayAndHour = (offset: number | null | undefined): { day: number; hour: number } => {
    if (offset === null || offset === undefined) {
        return { day: 0, hour: 0 }
    }
    const totalHours = Math.floor(offset / 3600)
    const day = Math.floor(totalHours / 24)
    const hour = totalHours % 24
    return { day, hour }
}

// Convert day and hour to interval_offset (seconds) for weekly exports
export const dayAndHourToIntervalOffset = (day: number, hour: number): number => {
    return day * 86400 + hour * 3600
}

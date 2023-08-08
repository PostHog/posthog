import { BatchExportConfiguration } from '~/types'

export function intervalToFrequency(interval: BatchExportConfiguration['interval']): string {
    return {
        day: 'daily',
        hour: 'hourly',
    }[interval]
}

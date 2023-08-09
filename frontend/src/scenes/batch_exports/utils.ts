import { BatchExportConfiguration, BatchExportRun } from '~/types'

export function intervalToFrequency(interval: BatchExportConfiguration['interval']): string {
    return {
        day: 'daily',
        hour: 'hourly',
    }[interval]
}

export function isRunInProgress(run: BatchExportRun): boolean {
    return ['Running', 'Starting'].includes(run.status)
}

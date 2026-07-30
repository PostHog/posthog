import { Dayjs, dayjs } from 'lib/dayjs'

import { DataModelingJob, DataModelingSyncInterval, OrNever } from '~/types'

/** One state per render of the status card; derived in materializationJobsLogic. */
export type MaterializationPanelState = 'suspended' | 'running' | 'failing' | 'healthy' | 'scheduled'

export const SYNC_FREQUENCY_OPTIONS: { value: DataModelingSyncInterval | OrNever; label: string }[] = [
    { value: 'never', label: 'manually only' },
    { value: '15min', label: 'every 15 minutes' },
    { value: '30min', label: 'every 30 minutes' },
    { value: '1hour', label: 'hourly' },
    { value: '6hour', label: 'every 6 hours' },
    { value: '12hour', label: 'every 12 hours' },
    { value: '24hour', label: 'daily' },
    { value: '7day', label: 'weekly' },
    { value: '30day', label: 'monthly' },
]

const SYNC_FREQUENCY_TO_MINUTES: Record<string, number> = {
    '5min': 5,
    '15min': 15,
    '30min': 30,
    '1hour': 60,
    '6hour': 360,
    '12hour': 720,
    '24hour': 1440,
    '7day': 10080,
    '30day': 43200,
}

export function syncFrequencyPhrase(syncFrequency: string | undefined | null): string | null {
    if (!syncFrequency || syncFrequency === 'never') {
        return null
    }
    return SYNC_FREQUENCY_OPTIONS.find((option) => option.value === syncFrequency)?.label ?? null
}

/** Best-effort next scheduled run: last run plus the interval. Null when unknown or unscheduled. */
export function estimateNextRunAt(
    lastRunAt: string | undefined | null,
    syncFrequency: string | undefined | null
): Dayjs | null {
    const minutes = syncFrequency ? SYNC_FREQUENCY_TO_MINUTES[syncFrequency] : undefined
    if (!lastRunAt || !minutes) {
        return null
    }
    const next = dayjs.utc(lastRunAt).add(minutes, 'minute')
    return next.isValid() ? next : null
}

export function jobDurationSeconds(job: DataModelingJob): number | null {
    if (!job.created_at || !job.last_run_at || job.status === 'Running') {
        return null
    }
    const seconds = (new Date(job.last_run_at).getTime() - new Date(job.created_at).getTime()) / 1000
    return seconds > 0 ? seconds : null
}

export function jobProgressPercent(job: DataModelingJob): number | null {
    if (!job.rows_expected || job.rows_expected <= 0) {
        return null
    }
    return Math.min(100, (job.rows_materialized / job.rows_expected) * 100)
}

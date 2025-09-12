import { dayjs } from 'lib/dayjs'

export function calculateTTL(recording_start_time: string, retention_period_days: number): number {
    const start = dayjs(recording_start_time)
    const now = dayjs()

    return Math.max(retention_period_days - now.diff(start, 'days'), 0)
}

import { SessionRecordingRetentionPeriod } from '~/types'

// 'legacy' is a project whose retention predates the setting, so it holds the pre-setting 30 days.
const RETENTION_PERIODS: Record<SessionRecordingRetentionPeriod, { days: number; label: string }> = {
    legacy: { days: 30, label: '30 days' },
    '30d': { days: 30, label: '30 days' },
    '90d': { days: 90, label: '90 days' },
    '1y': { days: 365, label: '1 year' },
    '5y': { days: 365 * 5, label: '5 years' },
}

// A project with no stored period keeps the default the backend applies.
const DEFAULT_RETENTION_PERIOD: SessionRecordingRetentionPeriod = '30d'

export function sessionRecordingRetentionDays(period: SessionRecordingRetentionPeriod | null | undefined): number {
    return RETENTION_PERIODS[period ?? DEFAULT_RETENTION_PERIOD].days
}

export function sessionRecordingRetentionLabel(period: SessionRecordingRetentionPeriod | null | undefined): string {
    return RETENTION_PERIODS[period ?? DEFAULT_RETENTION_PERIOD].label
}

import { SessionRecordingRetentionPeriod } from '~/types'

// 'legacy' is a project whose retention predates the setting, so it holds the pre-setting 30 days.
const RETENTION_PERIOD_DAYS: Record<SessionRecordingRetentionPeriod, number> = {
    legacy: 30,
    '30d': 30,
    '90d': 90,
    '1y': 365,
    '5y': 365 * 5,
}

const RETENTION_PERIOD_LABELS: Record<SessionRecordingRetentionPeriod, string> = {
    legacy: '30 days',
    '30d': '30 days',
    '90d': '90 days',
    '1y': '1 year',
    '5y': '5 years',
}

// A project with no stored period keeps the default the backend applies.
const DEFAULT_RETENTION_PERIOD: SessionRecordingRetentionPeriod = '30d'

export function sessionRecordingRetentionDays(period: SessionRecordingRetentionPeriod | null | undefined): number {
    return RETENTION_PERIOD_DAYS[period ?? DEFAULT_RETENTION_PERIOD]
}

export function sessionRecordingRetentionLabel(period: SessionRecordingRetentionPeriod | null | undefined): string {
    return RETENTION_PERIOD_LABELS[period ?? DEFAULT_RETENTION_PERIOD]
}

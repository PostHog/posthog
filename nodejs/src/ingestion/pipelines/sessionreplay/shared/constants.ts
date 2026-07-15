// '7d' is admin-only (not settable via the API or settings UI) but must be accepted here:
// the team service crashes the consumer on retention values it does not recognize.
export const ValidRetentionPeriods = ['7d', '30d', '90d', '1y', '5y'] as const

export type RetentionPeriod = (typeof ValidRetentionPeriods)[number]

export function isValidRetentionPeriod(retentionPeriod: string): retentionPeriod is RetentionPeriod {
    return ValidRetentionPeriods.includes(retentionPeriod as RetentionPeriod)
}

export const RetentionPeriodToDaysMap: { [key in RetentionPeriod]: number } = {
    '7d': 7,
    '30d': 30,
    '90d': 90,
    '1y': 365,
    '5y': 1825,
}

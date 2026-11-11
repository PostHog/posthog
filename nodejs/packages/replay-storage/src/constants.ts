export const ValidRetentionPeriods = ['30d', '90d', '1y', '5y'] as const

export type RetentionPeriod = (typeof ValidRetentionPeriods)[number]

export function isValidRetentionPeriod(retentionPeriod: string): retentionPeriod is RetentionPeriod {
    return ValidRetentionPeriods.includes(retentionPeriod as RetentionPeriod)
}

export const RetentionPeriodToDaysMap: { [key in RetentionPeriod]: number } = {
    '30d': 30,
    '90d': 90,
    '1y': 365,
    '5y': 1825,
}

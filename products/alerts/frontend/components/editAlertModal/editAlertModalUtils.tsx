import { IconLock } from '@posthog/icons'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

export function getSimulationRangeOptions(interval: AlertCalculationInterval): { label: string; value: string }[] {
    switch (interval) {
        case AlertCalculationInterval.REAL_TIME:
            return [
                { label: 'Last 10 minutes', value: '-10m' },
                { label: 'Last 1 hour', value: '-1h' },
                { label: 'Last 3 hours', value: '-3h' },
            ]
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return [
                { label: 'Last 12h', value: '-12h' },
                { label: 'Last 24h', value: '-24h' },
                { label: 'Last 48h', value: '-48h' },
                { label: 'Last 72h', value: '-72h' },
                { label: 'Last 7d', value: '-168h' },
            ]
        case AlertCalculationInterval.HOURLY:
            return [
                { label: 'Last 24h', value: '-24h' },
                { label: 'Last 48h', value: '-48h' },
                { label: 'Last 72h', value: '-72h' },
                { label: 'Last 7d', value: '-168h' },
            ]
        case AlertCalculationInterval.DAILY:
            return [
                { label: 'Last 14d', value: '-14d' },
                { label: 'Last 30d', value: '-30d' },
                { label: 'Last 60d', value: '-60d' },
                { label: 'Last 90d', value: '-90d' },
            ]
        case AlertCalculationInterval.WEEKLY:
            return [
                { label: 'Last 8w', value: '-8w' },
                { label: 'Last 12w', value: '-12w' },
                { label: 'Last 26w', value: '-26w' },
                { label: 'Last 52w', value: '-52w' },
            ]
        case AlertCalculationInterval.MONTHLY:
            return [
                { label: 'Last 6m', value: '-6m' },
                { label: 'Last 12m', value: '-12m' },
                { label: 'Last 24m', value: '-24m' },
            ]
    }
}

export function alertCalculationIntervalToLabel(interval: AlertCalculationInterval): string {
    switch (interval) {
        case AlertCalculationInterval.REAL_TIME:
            return 'in real time'
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return '15 minutes'
        case AlertCalculationInterval.HOURLY:
            return 'hour'
        case AlertCalculationInterval.DAILY:
            return 'day'
        case AlertCalculationInterval.WEEKLY:
            return 'week'
        case AlertCalculationInterval.MONTHLY:
            return 'month'
    }
}

export const ALERT_INTERVAL_OPTIONS: AlertCalculationInterval[] = [
    AlertCalculationInterval.HOURLY,
    AlertCalculationInterval.DAILY,
    AlertCalculationInterval.WEEKLY,
    AlertCalculationInterval.MONTHLY,
]

export function getAlertIntervalOptions(
    hasHighFrequencyAlertsEntitlement: boolean,
    hasRealTimeAlertsEntitlement: boolean,
    showRealTimeOption: boolean
): Array<{ label: string | JSX.Element; value: AlertCalculationInterval }> {
    const intervals = [
        ...(showRealTimeOption ? [AlertCalculationInterval.REAL_TIME] : []),
        AlertCalculationInterval.EVERY_15_MINUTES,
        ...ALERT_INTERVAL_OPTIONS,
    ]
    return intervals.map((interval) => {
        const labelText = alertCalculationIntervalToLabel(interval)
        const showLock =
            (interval === AlertCalculationInterval.EVERY_15_MINUTES && !hasHighFrequencyAlertsEntitlement) ||
            (interval === AlertCalculationInterval.REAL_TIME && !hasRealTimeAlertsEntitlement)
        return {
            label: showLock ? (
                <span className="flex items-center gap-1.5">
                    {labelText}
                    <IconLock className="text-muted text-base shrink-0" />
                </span>
            ) : (
                labelText
            ),
            value: interval,
        }
    })
}

import { IconLock } from '@posthog/icons'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

export function intervalDropdownPhrase(interval: AlertCalculationInterval): string {
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
    hasRealTimeAlertsEntitlement: boolean
): Array<{ label: string | JSX.Element; value: AlertCalculationInterval }> {
    const intervals = [
        AlertCalculationInterval.REAL_TIME,
        AlertCalculationInterval.EVERY_15_MINUTES,
        ...ALERT_INTERVAL_OPTIONS,
    ]
    return intervals.map((interval) => {
        const labelText = intervalDropdownPhrase(interval)
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

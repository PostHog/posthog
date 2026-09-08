import posthog from 'posthog-js'

import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { AvailableFeature, IntervalType } from '~/types'

export function getDefaultSimulationRange(interval: AlertCalculationInterval): string {
    switch (interval) {
        case AlertCalculationInterval.REAL_TIME:
            return '-1h'
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return '-12h'
        case AlertCalculationInterval.HOURLY:
            return '-48h'
        case AlertCalculationInterval.DAILY:
            return '-30d'
        case AlertCalculationInterval.WEEKLY:
            return '-12w'
        case AlertCalculationInterval.MONTHLY:
            return '-12m'
    }
}

export function getSimulationRangeOptions(interval: AlertCalculationInterval): { label: string; value: string }[] {
    switch (interval) {
        case AlertCalculationInterval.REAL_TIME:
            return [
                // Minutes are uppercase `M`; lowercase `m` is months. See `get_delta_mapping_for`.
                { label: 'Last 10 minutes', value: '-10M' },
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

export const HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE =
    '15-minute alert intervals require a Boost, Scale, or Enterprise platform add-on.'

const SUB_DAILY_INTERVALS = [
    AlertCalculationInterval.HOURLY,
    AlertCalculationInterval.EVERY_15_MINUTES,
    AlertCalculationInterval.REAL_TIME,
]

export function isSubDailyAlertInterval(interval: AlertCalculationInterval): boolean {
    return SUB_DAILY_INTERVALS.includes(interval)
}

const INTERVAL_DISPLAY_LABELS: Record<AlertCalculationInterval, string> = {
    [AlertCalculationInterval.REAL_TIME]: 'Real time',
    [AlertCalculationInterval.EVERY_15_MINUTES]: 'Every 15 minutes',
    [AlertCalculationInterval.HOURLY]: 'Hourly',
    [AlertCalculationInterval.DAILY]: 'Daily',
    [AlertCalculationInterval.WEEKLY]: 'Weekly',
    [AlertCalculationInterval.MONTHLY]: 'Monthly',
}

export function alertIntervalDisplayLabel(interval: AlertCalculationInterval): string {
    return INTERVAL_DISPLAY_LABELS[interval]
}

// Twin of _CADENCE_DURATION_MINUTES / _INTERVAL_DURATION_MINUTES in
// products/alerts/backend/evaluation/validation.py — keep the two in sync.
const CADENCE_DURATION_MINUTES: Record<AlertCalculationInterval, number> = {
    [AlertCalculationInterval.REAL_TIME]: 2,
    [AlertCalculationInterval.EVERY_15_MINUTES]: 15,
    [AlertCalculationInterval.HOURLY]: 60,
    [AlertCalculationInterval.DAILY]: 60 * 24,
    [AlertCalculationInterval.WEEKLY]: 60 * 24 * 7,
    [AlertCalculationInterval.MONTHLY]: 60 * 24 * 30,
}

export function alertCadenceMinutes(interval: AlertCalculationInterval): number {
    return CADENCE_DURATION_MINUTES[interval]
}

export const INSIGHT_INTERVAL_DURATION_MINUTES: Record<IntervalType, number> = {
    second: 1 / 60,
    minute: 1,
    hour: 60,
    day: 60 * 24,
    week: 60 * 24 * 7,
    month: 60 * 24 * 30,
    quarter: 60 * 24 * 30 * 3,
    year: 60 * 24 * 365,
}

/** An alert re-checks the insight's last completed bucket, whose size is the insight's grouping
 * interval. A cadence finer than that bucket re-reads the same frozen value until the bucket closes,
 * so evaluating the ongoing (incomplete) bucket is what makes the faster cadence meaningful. */
export function cadenceFinerThanInsightInterval(
    cadence: AlertCalculationInterval,
    insightInterval: string | null | undefined
): boolean {
    const insightMinutes =
        INSIGHT_INTERVAL_DURATION_MINUTES[(insightInterval as IntervalType | null) ?? 'day'] ??
        INSIGHT_INTERVAL_DURATION_MINUTES.day
    return alertCadenceMinutes(cadence) < insightMinutes
}

type EntitlementResult =
    | { blocked: true; message: string; feature: AvailableFeature }
    | { blocked: false; message: null; feature: null }

export function blockSubmitWithoutEntitlement(
    interval: AlertCalculationInterval,
    {
        hasHighFrequencyAlertsEntitlement,
        hasRealTimeAlertsEntitlement,
    }: { hasHighFrequencyAlertsEntitlement: boolean; hasRealTimeAlertsEntitlement: boolean }
): EntitlementResult {
    if (interval === AlertCalculationInterval.EVERY_15_MINUTES && !hasHighFrequencyAlertsEntitlement) {
        return {
            blocked: true,
            message: HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE,
            feature: AvailableFeature.HIGH_FREQUENCY_ALERTS,
        }
    }
    if (interval === AlertCalculationInterval.REAL_TIME && !hasRealTimeAlertsEntitlement) {
        return {
            blocked: true,
            message: 'Real-time alert intervals require a Scale or Enterprise plan.',
            feature: AvailableFeature.REAL_TIME_ALERTS,
        }
    }
    return { blocked: false, message: null, feature: null }
}

export function selectAlertCalculationInterval(
    value: AlertCalculationInterval,
    {
        guardAvailableFeature,
        onSelect,
        hasHighFrequencyAlertsEntitlement,
        hasRealTimeAlertsEntitlement,
    }: {
        guardAvailableFeature: GuardAvailableFeatureFn
        onSelect: (interval: AlertCalculationInterval) => void
        hasHighFrequencyAlertsEntitlement: boolean
        hasRealTimeAlertsEntitlement: boolean
    }
): boolean {
    if (value === AlertCalculationInterval.REAL_TIME) {
        posthog.capture('alert real time interval selected', {
            has_entitlement: hasRealTimeAlertsEntitlement,
        })
        return guardAvailableFeature(AvailableFeature.REAL_TIME_ALERTS, () => {
            onSelect(value)
        })
    }
    if (value === AlertCalculationInterval.EVERY_15_MINUTES) {
        posthog.capture('alert 15 min interval selected', {
            has_entitlement: hasHighFrequencyAlertsEntitlement,
        })
        return guardAvailableFeature(AvailableFeature.HIGH_FREQUENCY_ALERTS, () => {
            onSelect(value)
        })
    }
    onSelect(value)
    return true
}

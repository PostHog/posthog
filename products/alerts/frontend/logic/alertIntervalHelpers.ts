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

export const HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE =
    '15-minute alert intervals require a Boost, Scale, or Enterprise platform add-on.'

const REAL_TIME_ALERTS_REQUIRED_MESSAGE = 'Real-time alert intervals require a Scale or Enterprise plan.'

const HIGH_FREQUENCY_INTERVALS = [
    AlertCalculationInterval.HOURLY,
    AlertCalculationInterval.EVERY_15_MINUTES,
    AlertCalculationInterval.REAL_TIME,
]

export function isHighFrequencyAlertInterval(interval: AlertCalculationInterval): boolean {
    return HIGH_FREQUENCY_INTERVALS.includes(interval)
}

const CADENCE_DURATION_MINUTES: Record<AlertCalculationInterval, number> = {
    [AlertCalculationInterval.REAL_TIME]: 2,
    [AlertCalculationInterval.EVERY_15_MINUTES]: 15,
    [AlertCalculationInterval.HOURLY]: 60,
    [AlertCalculationInterval.DAILY]: 60 * 24,
    [AlertCalculationInterval.WEEKLY]: 60 * 24 * 7,
    [AlertCalculationInterval.MONTHLY]: 60 * 24 * 30,
}

const INSIGHT_INTERVAL_DURATION_MINUTES: Record<IntervalType, number> = {
    second: 1 / 60,
    minute: 1,
    hour: 60,
    day: 60 * 24,
    week: 60 * 24 * 7,
    month: 60 * 24 * 30,
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
    return CADENCE_DURATION_MINUTES[cadence] < insightMinutes
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
        return { blocked: true, message: REAL_TIME_ALERTS_REQUIRED_MESSAGE, feature: AvailableFeature.REAL_TIME_ALERTS }
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

import posthog from 'posthog-js'

import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { AvailableFeature } from '~/types'

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

export function isHighFrequencyAlertInterval(interval: AlertCalculationInterval): boolean {
    return (
        interval === AlertCalculationInterval.HOURLY ||
        interval === AlertCalculationInterval.EVERY_15_MINUTES ||
        interval === AlertCalculationInterval.REAL_TIME
    )
}

export function isRealTimeAlertInterval(interval: AlertCalculationInterval): boolean {
    return interval === AlertCalculationInterval.REAL_TIME
}

export const HIGH_FREQUENCY_ALERTS_REQUIRED_MESSAGE =
    '15-minute alert intervals require a Boost, Scale, or Enterprise platform add-on.'

export const REAL_TIME_ALERTS_REQUIRED_MESSAGE = 'Real-time alert intervals require a Scale or Enterprise plan.'

export function blockSubmitWithoutHighFrequencyAlertsEntitlement(
    interval: AlertCalculationInterval,
    hasHighFrequencyAlertsEntitlement: boolean
): boolean {
    return interval === AlertCalculationInterval.EVERY_15_MINUTES && !hasHighFrequencyAlertsEntitlement
}

export function blockSubmitWithoutRealTimeAlertsEntitlement(
    interval: AlertCalculationInterval,
    hasRealTimeAlertsEntitlement: boolean
): boolean {
    return interval === AlertCalculationInterval.REAL_TIME && !hasRealTimeAlertsEntitlement
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

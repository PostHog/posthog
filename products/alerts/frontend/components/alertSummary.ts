import { AlertCalculationInterval, AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { intervalDropdownPhrase } from 'products/alerts/frontend/components/editAlertModalUtils'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { type AlertConfig, type AlertType } from 'products/alerts/frontend/types'

export interface AlertSummaryParts {
    /** What the alert watches — e.g. "value below 100" or "anomalies". Empty when unknown. */
    fires: string
    /** How often it runs — e.g. "every day". Empty when unknown. */
    cadence: string
    /** Who it notifies — e.g. "2 people" or "2 people + Slack". Empty when none configured. */
    notifies: string
}

const ALERT_KIND_LABELS: Partial<Record<AlertConfig['type'], string>> = {
    TrendsAlertConfig: 'Trends',
    FunnelsAlertConfig: 'Funnels',
    HogQLAlertConfig: 'SQL',
}

export function formatNotificationSummary(subscribedCount: number, destinationCount: number): string {
    const parts: string[] = []
    if (subscribedCount > 0) {
        parts.push(`${subscribedCount} ${subscribedCount === 1 ? 'person' : 'people'}`)
    }
    if (destinationCount > 0) {
        parts.push(`${destinationCount} ${destinationCount === 1 ? 'destination' : 'destinations'}`)
    }
    return parts.join(' + ')
}

function boundForDisplay(value: number | undefined, thresholdType: InsightThresholdType): number | null {
    if (value == null || Number.isNaN(value)) {
        return null
    }
    return thresholdType === InsightThresholdType.PERCENTAGE ? value * 100 : value
}

export function formatThresholdSummary(
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType,
    lower: number | undefined,
    upper: number | undefined
): string {
    const lo = boundForDisplay(lower, thresholdType)
    const hi = boundForDisplay(upper, thresholdType)
    const both = lo != null && hi != null
    const unit = thresholdType === InsightThresholdType.PERCENTAGE ? '%' : ''
    switch (conditionType) {
        case AlertConditionType.RELATIVE_INCREASE:
            if (both) {
                return `increase outside ${lo}${unit} – ${hi}${unit}`
            }
            if (lo != null) {
                return `increase below ${lo}${unit}`
            }
            if (hi != null) {
                return `increase above ${hi}${unit}`
            }
            return 'increase breaches a threshold'
        case AlertConditionType.RELATIVE_DECREASE:
            if (both) {
                return `decrease outside ${lo}${unit} – ${hi}${unit}`
            }
            if (lo != null) {
                return `decrease below ${lo}${unit}`
            }
            if (hi != null) {
                return `decrease above ${hi}${unit}`
            }
            return 'decrease breaches a threshold'
        default:
            if (both) {
                return `value outside ${lo} – ${hi}`
            }
            if (lo != null) {
                return `value below ${lo}`
            }
            if (hi != null) {
                return `value above ${hi}`
            }
            return 'value breaches a threshold'
    }
}

function detectorSummary(): string {
    return 'an anomaly'
}

/** Build a one-line human summary of what an alert does. Pure (no React) so it can feed a header
 *  string, a wizard review step, or a tooltip. Returns empty parts when the form is too incomplete
 *  to summarize — the caller decides whether to render them at all. */
export function buildAlertSummary(
    alertForm: AlertFormType | AlertType,
    subscribedCount: number,
    destinationCount = 0
): AlertSummaryParts {
    const alertMode = alertForm.detector_config ? 'detector' : 'threshold'

    let fires = ''
    if (alertMode === 'detector') {
        fires = detectorSummary()
    } else {
        const bounds = alertForm.threshold?.configuration?.bounds
        fires = formatThresholdSummary(
            alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE,
            alertForm.threshold?.configuration?.type ?? InsightThresholdType.ABSOLUTE,
            bounds?.lower,
            bounds?.upper
        )
    }

    let cadence = ''
    if (alertForm.calculation_interval) {
        const phrase = intervalDropdownPhrase(alertForm.calculation_interval)
        cadence =
            alertForm.calculation_interval === AlertCalculationInterval.REAL_TIME ? `in real time` : `every ${phrase}`
    }

    const notifies = formatNotificationSummary(subscribedCount, destinationCount)

    return { fires, cadence, notifies }
}

/** Short label for the alert kind — used by the header to hint what's being monitored. */
export function alertKindLabel(alertForm: AlertFormType | AlertType | null | undefined): string | null {
    if (!alertForm) {
        return null
    }
    const config = alertForm.config
    if (!config) {
        return null
    }
    return ALERT_KIND_LABELS[config.type] ?? null
}

import { AlertCalculationInterval, AlertConditionType } from '~/queries/schema/schema-general'

import { intervalDropdownPhrase } from 'products/alerts/frontend/components/editAlertModalUtils'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import {
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
    type AlertType,
} from 'products/alerts/frontend/types'

export interface AlertSummaryParts {
    /** What the alert watches — e.g. "value below 100" or "anomalies". Empty when unknown. */
    fires: string
    /** How often it runs — e.g. "every day". Empty when unknown. */
    cadence: string
    /** Who it notifies — e.g. "2 people" or "2 people + Slack". Empty when none configured. */
    notifies: string
}

function formatBound(value: number | undefined): string | null {
    return value == null || Number.isNaN(value) ? null : String(value)
}

function thresholdSummaryParts(
    conditionType: AlertConditionType,
    lower: number | undefined,
    upper: number | undefined
): string {
    const lo = formatBound(lower)
    const hi = formatBound(upper)
    const both = lo != null && hi != null
    switch (conditionType) {
        case AlertConditionType.RELATIVE_INCREASE:
            if (both) {
                return `value increases by ${lo}%–${hi}%`
            }
            if (lo != null) {
                return `value increases by ${lo}%`
            }
            if (hi != null) {
                return `value increases by up to ${hi}%`
            }
            return 'value increases'
        case AlertConditionType.RELATIVE_DECREASE:
            if (both) {
                return `value decreases by ${lo}%–${hi}%`
            }
            if (lo != null) {
                return `value decreases by ${lo}%`
            }
            if (hi != null) {
                return `value decreases by up to ${hi}%`
            }
            return 'value decreases'
        default:
            if (both) {
                return `value outside ${lo}–${hi}`
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
export function buildAlertSummary(alertForm: AlertFormType, subscribedCount: number): AlertSummaryParts {
    const alertMode = alertForm.detector_config ? 'detector' : 'threshold'

    let fires = ''
    if (alertMode === 'detector') {
        fires = detectorSummary()
    } else {
        const bounds = alertForm.threshold?.configuration?.bounds
        fires = thresholdSummaryParts(
            alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE,
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

    let notifies = ''
    if (subscribedCount > 0) {
        notifies = `${subscribedCount} ${subscribedCount === 1 ? 'person' : 'people'}`
    }

    return { fires, cadence, notifies }
}

/** Short label for the alert kind — used by the header to hint what's being monitored. */
export function alertKindLabel(alertForm: AlertFormType | AlertType | null | undefined): string | null {
    if (!alertForm) {
        return null
    }
    const config = (alertForm as AlertFormType).config
    if (!config) {
        return null
    }
    if (isTrendsAlertConfig(config)) {
        return 'Trends'
    }
    if (isFunnelsAlertConfig(config)) {
        return 'Funnels'
    }
    if (isHogQLAlertConfig(config)) {
        return 'SQL'
    }
    return null
}

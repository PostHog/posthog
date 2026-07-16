import { AlertConditionType, InsightsThresholdBounds, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertConfig, isFunnelsAlertConfig } from '../types'
import { hasThresholdBounds, valueBreachesBounds } from './alertPreviewShared'

export interface FunnelAlertPreviewValue {
    label: string | null // breakdown value; null for a non-breakdown funnel
    rate: number // 0–100 — the period the alert evaluates (latest, or last complete for relative)
    breaching: boolean
    previousRate?: number // relative only: the prior period's rate the change is measured against
}

/** Advisory preview, mirroring the backend funnel strategies
 * (products/alerts/backend/evaluation/funnel_strategies.py) — keep in sync if you change the backend math. */
export type FunnelAlertPreview =
    | { status: 'no-data' }
    // `relative`: the alert fires on the period-over-period change. The values carry the last complete
    // period and the one before it, and `breaching` reflects the change against the threshold.
    | { status: 'ok'; values: FunnelAlertPreviewValue[]; isBreakdown: boolean; hasBounds: boolean; relative?: boolean }

/** Period-over-period change the alert evaluates, mirroring the backend comparator's `_relative_value`:
 * an absolute threshold compares the raw percentage-point change; a percentage threshold the ratio. */
function _relativeChange(
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType | undefined,
    anchor: number,
    previous: number
): number {
    const numerator = conditionType === AlertConditionType.RELATIVE_INCREASE ? anchor - previous : previous - anchor
    if (thresholdType !== InsightThresholdType.PERCENTAGE) {
        return numerator
    }
    if (previous === 0) {
        return anchor === 0 ? 0 : Infinity
    }
    return numerator / previous
}

interface FunnelStep {
    count: number
    breakdown_value?: unknown
}

// A trends funnel series is a conversion-rate time series, not a step list: `data` holds the 0–100
// rate per period. A gap period can be null; the backend maps it to None and skips it, so the preview
// treats a null anchor as no-data rather than reading it as a (potentially breaching) 0.
interface FunnelTrendsSeries {
    data?: (number | null)[]
    breakdown_value?: unknown
}

function _deriveTrendsPreview(
    series: FunnelTrendsSeries[],
    bounds: InsightsThresholdBounds | null | undefined,
    thresholdType: InsightThresholdType | undefined,
    conditionType: AlertConditionType | undefined,
    checkOngoing: boolean
): FunnelAlertPreview {
    const relative =
        conditionType === AlertConditionType.RELATIVE_INCREASE || conditionType === AlertConditionType.RELATIVE_DECREASE
    const values: FunnelAlertPreviewValue[] = series.map((s) => {
        const data = s.data ?? []
        const label = _breakdownLabel(s.breakdown_value)
        // By default the latest period is still in progress, so anchor on the last complete one;
        // check_ongoing_interval anchors on the latest. Clamped to 0 like the backend's
        // `max(len - 1 if ongoing else len - 2, 0)`.
        const anchorIndex = Math.max(checkOngoing ? data.length - 1 : data.length - 2, 0)
        const anchor = data[anchorIndex]
        // The backend skips a null/gap anchor period (no fire); mirror that rather than reading it as 0.
        if (typeof anchor !== 'number') {
            return { label, rate: 0, breaching: false }
        }
        if (!relative) {
            return { label, rate: anchor, breaching: valueBreachesBounds(anchor, bounds) }
        }
        // Relative: diff the anchor against the period before it (same as the backend comparator).
        const prev = anchorIndex >= 1 ? data[anchorIndex - 1] : undefined
        const previousRate = typeof prev === 'number' ? prev : undefined
        const breaching =
            previousRate === undefined
                ? false
                : valueBreachesBounds(_relativeChange(conditionType!, thresholdType, anchor, previousRate), bounds)
        return { label, rate: anchor, previousRate, breaching }
    })
    return {
        status: 'ok',
        values,
        isBreakdown: series.length > 1,
        hasBounds: hasThresholdBounds(bounds),
        ...(relative ? { relative: true } : {}),
    }
}

const _conversionRate = (steps: FunnelStep[], stepIndex: number, fromPrevious: boolean): number | null => {
    if (stepIndex < 0 || stepIndex >= steps.length) {
        return null
    }
    const baseIndex = fromPrevious ? stepIndex - 1 : 0
    if (baseIndex < 0) {
        return null // conversion_from_previous is undefined at the first step
    }
    const base = steps[baseIndex]?.count ?? 0
    const target = steps[stepIndex]?.count ?? 0
    return base === 0 ? 0 : (target / base) * 100
}

const _breakdownLabel = (breakdown: unknown): string | null => {
    if (breakdown == null) {
        return null
    }
    return Array.isArray(breakdown) ? breakdown.join(', ') : String(breakdown)
}

// Current unless explicitly tagged as another compare period; non-compared rows have no label.
// Positive check so any future compare label is excluded too.
const _isCurrentPeriodRow = (row: any): boolean =>
    row == null || typeof row !== 'object' || row.compare_label == null || row.compare_label === 'current'

/** Keep only current-period rows from a compare-enabled funnel result (mirror of the backend's
 * `_current_period_only`); no-op when compare is off. */
function _currentPeriodOnly(result: any[]): any[] {
    if (Array.isArray(result[0])) {
        // Breakdown: the runner emits previous-period breakdowns as their own groups that filter to
        // empty — drop them, or they'd surface as a misleading whole-preview "no-data".
        return result
            .map((steps) => (Array.isArray(steps) ? steps.filter((row) => _isCurrentPeriodRow(row)) : steps))
            .filter((steps) => !Array.isArray(steps) || steps.length > 0)
    }
    return result.filter((row) => _isCurrentPeriodRow(row))
}

export function deriveFunnelAlertPreview(
    insightData: Record<string, any> | null,
    config: AlertConfig | null | undefined,
    bounds: InsightsThresholdBounds | null | undefined,
    isTrendsFunnel: boolean,
    conditionType?: AlertConditionType,
    thresholdType?: InsightThresholdType
): FunnelAlertPreview | null {
    if (!isFunnelsAlertConfig(config)) {
        return null
    }
    const rawResult = insightData?.result
    if (!Array.isArray(rawResult) || rawResult.length === 0) {
        return null // No result loaded yet — fall back to the static hint
    }
    // Compare-enabled funnels concatenate current + previous period rows (tagged compare_label).
    // Alerts evaluate the current period, so drop previous rows before normalizing (mirrors the backend).
    const result = _currentPeriodOnly(rawResult)
    if (result.length === 0) {
        // Data existed but was all previous-period (compare on, no current rows) — show no-data, not
        // the "not loaded yet" hint.
        return { status: 'no-data' }
    }
    // A trends funnel returns conversion-rate time series rather than step lists.
    if (isTrendsFunnel) {
        return _deriveTrendsPreview(result, bounds, thresholdType, conditionType, !!config.check_ongoing_interval)
    }
    // A non-breakdown funnel returns list[step]; a breakdown funnel returns list[list[step]].
    const isBreakdown = Array.isArray(result[0])
    const breakdowns: FunnelStep[][] = isBreakdown ? result : [result]
    if (breakdowns.some((steps) => !Array.isArray(steps) || steps.length === 0)) {
        return { status: 'no-data' }
    }

    const fromPrevious = config.metric === 'conversion_from_previous'
    const values: FunnelAlertPreviewValue[] = []
    for (const steps of breakdowns) {
        const stepIndex = config.funnel_step ?? steps.length - 1
        const rate = _conversionRate(steps, stepIndex, fromPrevious)
        if (rate === null) {
            return null // out-of-range / undefined config — the picker and validation prevent this
        }
        values.push({
            label: _breakdownLabel(steps[0]?.breakdown_value),
            rate,
            breaching: valueBreachesBounds(rate, bounds),
        })
    }
    return { status: 'ok', values, isBreakdown, hasBounds: hasThresholdBounds(bounds) }
}

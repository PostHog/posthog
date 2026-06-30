import { AlertConditionType, InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { hasThresholdBounds, valueBreachesBounds } from './alertPreviewShared'
import { AlertConfig, isFunnelsAlertConfig } from './types'

export interface FunnelAlertPreviewValue {
    label: string | null // breakdown value; null for a non-breakdown funnel
    rate: number // 0–100
    breaching: boolean
}

/** Advisory preview, mirroring the backend funnel strategies
 * (products/alerts/backend/evaluation/funnel_strategies.py) — keep in sync if you change the backend math. */
export type FunnelAlertPreview =
    | { status: 'no-data' }
    // `relative`: the alert fires on the period-over-period change, so the breach verdict can't be
    // previewed from a single rate — the banner shows the latest rate without an absolute ok/breach tag.
    | { status: 'ok'; values: FunnelAlertPreviewValue[]; isBreakdown: boolean; hasBounds: boolean; relative?: boolean }

interface FunnelStep {
    count: number
    breakdown_value?: unknown
}

// A trends funnel series is a conversion-rate time series, not a step list: `data` holds the 0–100
// rate per period. The alert evaluates the latest period, so the preview reads the last point. A gap
// period can be null, so coerce non-numbers to 0 (the runner already fills 0) to match the backend.
interface FunnelTrendsSeries {
    data?: (number | null)[]
    breakdown_value?: unknown
}

function _deriveTrendsPreview(
    series: FunnelTrendsSeries[],
    bounds: InsightsThresholdBounds | null | undefined,
    relative: boolean
): FunnelAlertPreview {
    const values: FunnelAlertPreviewValue[] = series.map((s) => {
        const last = s.data?.[s.data.length - 1]
        const rate = typeof last === 'number' ? last : 0
        // A relative alert fires on the change vs the prior period, not the absolute rate — don't
        // claim an absolute breach the alert wouldn't actually evaluate.
        return {
            label: _breakdownLabel(s.breakdown_value),
            rate,
            breaching: relative ? false : valueBreachesBounds(rate, bounds),
        }
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
    conditionType?: AlertConditionType
): FunnelAlertPreview | null {
    const isRelative =
        conditionType === AlertConditionType.RELATIVE_INCREASE || conditionType === AlertConditionType.RELATIVE_DECREASE
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
    // A trends funnel returns conversion-rate time series rather than step lists; read the latest period.
    if (isTrendsFunnel) {
        return _deriveTrendsPreview(result, bounds, isRelative)
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

import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { hasThresholdBounds, valueBreachesBounds } from './alertPreviewShared'
import { AlertConfig, isFunnelsAlertConfig } from './types'

export interface FunnelAlertPreviewValue {
    label: string | null // breakdown value; null for a non-breakdown funnel
    rate: number // 0–100
    breaching: boolean
}

/** Advisory preview, mirroring the backend `_conversion_rate`/`_steps_per_breakdown`
 * (products/alerts/backend/evaluation/funnels.py) — keep in sync if you change the backend math. */
export type FunnelAlertPreview =
    | { status: 'no-data' }
    | { status: 'ok'; values: FunnelAlertPreviewValue[]; isBreakdown: boolean; hasBounds: boolean }

interface FunnelStep {
    count: number
    breakdown_value?: unknown
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

const _breakdownLabel = (steps: FunnelStep[]): string | null => {
    const breakdown = steps[0]?.breakdown_value
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
        return result.map((steps) => (Array.isArray(steps) ? steps.filter((row) => _isCurrentPeriodRow(row)) : steps))
    }
    return result.filter((row) => _isCurrentPeriodRow(row))
}

export function deriveFunnelAlertPreview(
    insightData: Record<string, any> | null,
    config: AlertConfig | null | undefined,
    bounds: InsightsThresholdBounds | null | undefined
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
        values.push({ label: _breakdownLabel(steps), rate, breaching: valueBreachesBounds(rate, bounds) })
    }
    return { status: 'ok', values, isBreakdown, hasBounds: hasThresholdBounds(bounds) }
}

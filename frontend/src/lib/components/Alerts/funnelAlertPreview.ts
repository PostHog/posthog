import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { AlertConfig, isFunnelsAlertConfig } from './types'

/** One conversion rate the alert would evaluate right now, with whether it breaches the threshold. */
export interface FunnelAlertPreviewValue {
    /** Breakdown value label; null for a non-breakdown funnel. */
    label: string | null
    /** Conversion rate, 0–100. */
    rate: number
    /** Whether this rate breaches the configured absolute bounds right now. */
    breaching: boolean
}

/** What a funnel alert would evaluate right now — the conversion rate(s) at the configured step, plus
 * whether each breaches the current threshold. Mirrors the backend `_conversion_rate`/`_steps_per_breakdown`
 * (products/alerts/backend/evaluation/funnels.py) so the modal can preview the value (and a fires/ok
 * read-out) before the first run. Advisory only — the extractor is the evaluation-time authority; if you
 * change the backend math, update this too. */
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

export function deriveFunnelAlertPreview(
    insightData: Record<string, any> | null,
    config: AlertConfig | null | undefined,
    bounds: InsightsThresholdBounds | null | undefined
): FunnelAlertPreview | null {
    if (!isFunnelsAlertConfig(config)) {
        return null
    }
    const result = insightData?.result
    if (!Array.isArray(result) || result.length === 0) {
        return null // No result loaded yet — fall back to the static hint
    }
    // A non-breakdown funnel returns list[step]; a breakdown funnel returns list[list[step]].
    const isBreakdown = Array.isArray(result[0])
    const breakdowns: FunnelStep[][] = isBreakdown ? result : [result]
    if (breakdowns.some((steps) => !Array.isArray(steps) || steps.length === 0)) {
        return { status: 'no-data' }
    }

    const fromPrevious = config.metric === 'conversion_from_previous'
    const hasBounds = !!bounds && (bounds.lower != null || bounds.upper != null)
    const values: FunnelAlertPreviewValue[] = []
    for (const steps of breakdowns) {
        const stepIndex = config.funnel_step ?? steps.length - 1
        const rate = _conversionRate(steps, stepIndex, fromPrevious)
        if (rate === null) {
            return null // out-of-range / undefined config — the picker and validation prevent this
        }
        const breaching =
            (bounds?.lower != null && rate < bounds.lower) || (bounds?.upper != null && rate > bounds.upper)
        values.push({ label: _breakdownLabel(steps), rate, breaching })
    }
    return { status: 'ok', values, isBreakdown, hasBounds }
}

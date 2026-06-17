import { AlertConfig, isFunnelsAlertConfig } from './types'

/** What a funnel alert would evaluate right now — the conversion rate(s) at the configured step.
 * Mirrors the backend `_conversion_rate`/`_steps_per_breakdown` (products/alerts/backend/evaluation/funnels.py)
 * so the modal can preview the value the alert checks before the first run. Advisory only — the
 * extractor is the evaluation-time authority; if you change the backend math, update this too. */
export type FunnelAlertPreview = { status: 'no-data' } | { status: 'ok'; rates: number[]; isBreakdown: boolean }

interface FunnelStep {
    count: number
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

export function deriveFunnelAlertPreview(
    insightData: Record<string, any> | null,
    config: AlertConfig | null | undefined
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
    const rates: number[] = []
    for (const steps of breakdowns) {
        const stepIndex = config.funnel_step ?? steps.length - 1
        const rate = _conversionRate(steps, stepIndex, fromPrevious)
        if (rate === null) {
            return null // out-of-range / undefined config — the picker and validation prevent this
        }
        rates.push(rate)
    }
    return { status: 'ok', rates, isBreakdown }
}

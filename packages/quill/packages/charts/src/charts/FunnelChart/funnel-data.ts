import type { Series } from '../../core/types'

export const RATE_TO_PERCENT = 100

/** Conversion of a step's count against a basis count, as a 0..1 rate. A zero or absent basis
 *  yields 0 (rather than dividing by zero) so the bar collapses instead of rendering NaN. */
export function funnelConversionRate(count: number, basisCount: number): number {
    return basisCount > 0 ? count / basisCount : 0
}

export interface FunnelStepCount {
    label: string
    count: number
}

export interface FunnelFromCountsOptions {
    key?: string
    label?: string
    color?: string
}

/** Builds the `steps` + single-`series` pair for a no-breakdown funnel from raw step counts,
 *  with each step valued as its conversion from the first step (percent, 0–100). Multi-variant
 *  funnels resolve their own per-variant percentages and pass
 *  `Series[]` directly. */
export function funnelFromCounts(
    steps: FunnelStepCount[],
    options: FunnelFromCountsOptions = {}
): { steps: string[]; series: Series[] } {
    const firstCount = steps[0]?.count ?? 0
    return {
        steps: steps.map((step) => step.label),
        series: [
            {
                key: options.key ?? 'funnel-conversion',
                label: options.label ?? 'Conversion',
                color: options.color,
                data: steps.map((step) => funnelConversionRate(step.count, firstCount) * RATE_TO_PERCENT),
            },
        ],
    }
}

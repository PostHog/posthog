import type { BarShadow } from '../../../core/canvas-renderer'
import { DEFAULT_MARGINS, X_AXIS_TITLE_MARGIN } from '../../../core/hooks/useChartMargins'
import type { BarsConfig } from '../../../core/types'

// Negative offsetY casts the shadow upward onto the visible track above the bar.
export const DEFAULT_BAR_SHADOW: BarShadow = { color: 'rgba(0,0,0,0.30)', blur: 12, offsetY: -4 }

// Horizontal floor: each row gets at least this much px so tick labels don't crush; wrapper scrolls.
export const HORIZONTAL_MIN_BAND_SIZE_DEFAULT = 24
// Reserve room for chart-edge margins + worst-case x-axis title margin (matches useChartMargins).
export const HORIZONTAL_CHART_MARGIN_PX = DEFAULT_MARGINS.top + DEFAULT_MARGINS.bottom + X_AXIS_TITLE_MARGIN

export function resolveBarShadow(barShadow: BarsConfig['shadow']): BarShadow | undefined {
    if (barShadow === true) {
        return DEFAULT_BAR_SHADOW
    }
    if (barShadow === false || barShadow == null) {
        return undefined
    }
    return barShadow
}

/** Minimum wrapper height for a horizontal bar chart so each band keeps `resolvedMinBandSize`
 *  px and tick labels don't crush — the wrapper scrolls past this. Returns `undefined` when
 *  the floor doesn't apply (vertical, no floor, or no bands). */
export function computeWrapperMinHeight({
    isHorizontal,
    resolvedMinBandSize,
    labels,
}: {
    isHorizontal: boolean
    resolvedMinBandSize: number
    labels: string[]
}): number | undefined {
    if (!isHorizontal || resolvedMinBandSize <= 0) {
        return undefined
    }
    const uniqueBands = new Set(labels).size
    if (uniqueBands === 0) {
        return undefined
    }
    return uniqueBands * resolvedMinBandSize + HORIZONTAL_CHART_MARGIN_PX
}

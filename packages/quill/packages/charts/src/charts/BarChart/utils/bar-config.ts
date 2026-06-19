import type { BarShadow } from '../../../core/canvas-renderer'
import { DEFAULT_MARGINS, X_AXIS_TITLE_MARGIN } from '../../../core/hooks/useChartMargins'
import type { BarsConfig } from '../../../core/types'

// Negative offsetY casts the shadow upward onto the visible track above the bar.
const DEFAULT_BAR_SHADOW: BarShadow = { color: 'rgba(0,0,0,0.30)', blur: 12, offsetY: -4 }

// Horizontal floor: each row gets at least this much px so tick labels don't crush; wrapper scrolls.
export const HORIZONTAL_MIN_BAND_SIZE_DEFAULT = 24
// Reserve room for chart-edge margins + worst-case x-axis title margin (matches useChartMargins).
const HORIZONTAL_CHART_MARGIN_PX = DEFAULT_MARGINS.top + DEFAULT_MARGINS.bottom + X_AXIS_TITLE_MARGIN

export function resolveBarShadow(barShadow: BarsConfig['shadow']): BarShadow | undefined {
    if (barShadow === true) {
        return DEFAULT_BAR_SHADOW
    }
    if (barShadow === false || barShadow == null) {
        return undefined
    }
    return barShadow
}

export interface WrapperMinHeightOptions {
    isHorizontal: boolean
    fitToHeight: boolean
    resolvedMinBandSize: number
    labels: string[]
}

// fit-to-height returns no floor: it drops overflow rows instead of growing the wrapper.
export function computeWrapperMinHeight({
    isHorizontal,
    fitToHeight,
    resolvedMinBandSize,
    labels,
}: WrapperMinHeightOptions): number | undefined {
    if (!isHorizontal || fitToHeight || resolvedMinBandSize <= 0) {
        return undefined
    }
    const uniqueBands = new Set(labels).size
    if (uniqueBands === 0) {
        return undefined
    }
    return uniqueBands * resolvedMinBandSize + HORIZONTAL_CHART_MARGIN_PX
}

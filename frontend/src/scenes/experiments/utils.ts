import { getSeriesColor } from 'lib/colors'
import { FunnelLayout } from 'lib/constants'

import { ChartDisplayType, FilterType, FunnelVizType, InsightType } from '~/types'

export function getExperimentInsightColour(variantIndex: number | null): string {
    return variantIndex !== null ? getSeriesColor(variantIndex) : 'var(--muted-3000)'
}

export const transformResultFilters = (filters: Partial<FilterType>): Partial<FilterType> => ({
    ...filters,
    ...(filters.insight === InsightType.FUNNELS && {
        layout: FunnelLayout.vertical,
        funnel_viz_type: FunnelVizType.Steps,
    }),
    ...(filters.insight === InsightType.TRENDS && {
        display: ChartDisplayType.ActionsLineGraphCumulative,
    }),
})

export function findKeyWithHighestNumber(obj: Record<string, number> | null): string | null {
    if (!obj) {
        return null
    }

    let highestValue = -Infinity
    let keyWithHighestValue = null

    Object.keys(obj).forEach((key) => {
        if (obj[key] > highestValue) {
            highestValue = obj[key]
            keyWithHighestValue = key
        }
    })

    return keyWithHighestValue
}

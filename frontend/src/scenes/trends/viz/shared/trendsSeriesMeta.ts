import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import type { ActionFilter } from '~/types'

export type TrendsSeriesMeta = {
    action?: ActionFilter
    breakdown_value?: string | number | string[]
    compare_label?: SeriesDatum['compare_label']
    days?: string[]
    order?: number
    filter?: SeriesDatum['filter']
}

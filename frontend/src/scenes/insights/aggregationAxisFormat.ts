import { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'

import { TrendsFilter } from '~/queries/schema'
import { ChartDisplayType, TrendsFilterType } from '~/types'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled'] as const
export type AggregationAxisFormat = (typeof formats)[number]

export const INSIGHT_UNIT_OPTIONS: LemonSelectOptionLeaf<AggregationAxisFormat>[] = [
    { value: 'numeric', label: 'None' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'percentage', label: 'Percent (0-100)' },
    { value: 'percentage_scaled', label: 'Percent (0-1)' },
]

export const formatAggregationAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string
): string => {
    value = Number(value)
    let formattedValue = humanFriendlyNumber(value, trendsFilter?.decimal_places)
    if (trendsFilter?.aggregation_axis_format) {
        switch (trendsFilter?.aggregation_axis_format) {
            case 'duration':
                formattedValue = humanFriendlyDuration(value)
                break
            case 'duration_ms':
                formattedValue = humanFriendlyDuration(value / 1000)
                break
            case 'percentage':
                formattedValue = percentage(value / 100)
                break
            case 'percentage_scaled':
                formattedValue = percentage(value)
                break
            case 'numeric': // numeric is default
            default:
                break
        }
    }
    return `${trendsFilter?.aggregation_axis_prefix || ''}${formattedValue}${
        trendsFilter?.aggregation_axis_postfix || ''
    }`
}

export const formatPercentStackAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string,
    isPercentStackView: boolean
): string => {
    if (isPercentStackView) {
        value = Number(value)
        return percentage(value / 100)
    } else {
        return formatAggregationAxisValue(trendsFilter, value)
    }
}

export const axisLabel = (chartDisplayType: ChartDisplayType | null | undefined): string => {
    switch (chartDisplayType) {
        case ChartDisplayType.ActionsLineGraph:
        case ChartDisplayType.ActionsLineGraphCumulative:
        case ChartDisplayType.ActionsBar:
            return 'Y-axis unit'
        case ChartDisplayType.ActionsBarValue:
            return 'X-axis unit'
        default:
            return 'Unit'
    }
}

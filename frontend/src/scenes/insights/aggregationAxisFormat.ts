import { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { DEFAULT_DECIMAL_PLACES, humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'

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

// this function needs to support a trendsFilter as part of an insight query and
// legacy trend filters, as we still return these as part of a data response
export const formatAggregationAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string
): string => {
    value = Number(value)
    const decimalPlaces =
        (trendsFilter as TrendsFilter)?.decimalPlaces ??
        (trendsFilter as Partial<TrendsFilterType>)?.decimal_places ??
        DEFAULT_DECIMAL_PLACES
    const aggregationAxisFormat =
        (trendsFilter as TrendsFilter)?.aggregationAxisFormat ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_format
    const aggregationAxisPrefix =
        (trendsFilter as TrendsFilter)?.aggregationAxisPrefix ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_prefix
    const aggregationAxisPostfix =
        (trendsFilter as TrendsFilter)?.aggregationAxisPostfix ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_postfix
    let formattedValue = humanFriendlyNumber(value, decimalPlaces)
    if (aggregationAxisFormat) {
        switch (aggregationAxisFormat) {
            case 'duration':
                formattedValue = humanFriendlyDuration(value, undefined, decimalPlaces)
                break
            case 'duration_ms':
                formattedValue = humanFriendlyDuration(value / 1000, undefined, decimalPlaces)
                break
            case 'percentage':
                formattedValue = percentage(value / 100, decimalPlaces, !!decimalPlaces)
                break
            case 'percentage_scaled':
                formattedValue = percentage(value, decimalPlaces, !!decimalPlaces)
                break
            case 'numeric': // numeric is default
            default:
                break
        }
    }
    return `${aggregationAxisPrefix || ''}${formattedValue}${aggregationAxisPostfix || ''}`
}

export const formatPercentStackAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string,
    isPercentStackView: boolean
): string => {
    if (isPercentStackView) {
        value = Number(value)
        return percentage(value / 100)
    }
    return formatAggregationAxisValue(trendsFilter, value)
}

export const axisLabel = (chartDisplayType: ChartDisplayType | null | undefined): string => {
    switch (chartDisplayType) {
        case ChartDisplayType.ActionsLineGraph:
        case ChartDisplayType.ActionsLineGraphCumulative:
        case ChartDisplayType.ActionsBar:
        case ChartDisplayType.ActionsAreaGraph:
            return 'Y-axis unit'
        case ChartDisplayType.ActionsBarValue:
            return 'X-axis unit'
        default:
            return 'Unit'
    }
}

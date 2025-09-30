import { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { humanFriendlyCurrency, humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'

import { TrendsFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, TrendsFilterType } from '~/types'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled', 'currency'] as const
export type AggregationAxisFormat = (typeof formats)[number]

export const INSIGHT_UNIT_OPTIONS: LemonSelectOptionLeaf<AggregationAxisFormat>[] = [
    { value: 'numeric', label: 'None' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'percentage', label: 'Percent (0-100)' },
    { value: 'percentage_scaled', label: 'Percent (0-1)' },
    { value: 'currency', label: 'Currency ($)' },
]

// this function needs to support a trendsFilter as part of an insight query and
// legacy trend filters, as we still return these as part of a data response
export const formatAggregationAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string
): string => {
    value = Number(value)
    const maxDecimalPlaces =
        (trendsFilter as TrendsFilter)?.decimalPlaces ?? (trendsFilter as Partial<TrendsFilterType>)?.decimal_places
    const minDecimalPlaces =
        (trendsFilter as TrendsFilter)?.minDecimalPlaces ??
        (trendsFilter as Partial<TrendsFilterType>)?.min_decimal_places
    const aggregationAxisFormat =
        (trendsFilter as TrendsFilter)?.aggregationAxisFormat ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_format
    const aggregationAxisPrefix =
        (trendsFilter as TrendsFilter)?.aggregationAxisPrefix ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_prefix
    const aggregationAxisPostfix =
        (trendsFilter as TrendsFilter)?.aggregationAxisPostfix ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_postfix
    let formattedValue = humanFriendlyNumber(value, maxDecimalPlaces, minDecimalPlaces)
    if (aggregationAxisFormat) {
        switch (aggregationAxisFormat) {
            case 'duration':
                formattedValue = humanFriendlyDuration(value)
                break
            case 'duration_ms':
                formattedValue = humanFriendlyDuration(value / 1000, { secondsFixed: 1 })
                break
            case 'percentage':
                formattedValue = percentage(value / 100)
                break
            case 'percentage_scaled':
                formattedValue = percentage(value)
                break
            case 'currency':
                formattedValue = humanFriendlyCurrency(value)
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
        case ChartDisplayType.ActionsUnstackedBar:
        case ChartDisplayType.ActionsAreaGraph:
            return 'Y-axis unit'
        case ChartDisplayType.ActionsBarValue:
            return 'X-axis unit'
        default:
            return 'Unit'
    }
}

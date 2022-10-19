import { LemonSelectOption } from 'lib/components/LemonSelect'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ChartDisplayType, FilterType } from '~/types'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled'] as const
export type AggregationAxisFormat = typeof formats[number]

export const aggregationAxisFormatSelectOptions: LemonSelectOption<AggregationAxisFormat>[] = [
    { value: 'numeric', label: 'None' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'percentage', label: 'Percent (0-100)' },
    { value: 'percentage_scaled', label: 'Percent (0-1)' },
]

export const formatAggregationAxisValue = (
    filters: Partial<FilterType> | undefined,
    value: number | string
): string => {
    value = Number(value)
    let formattedValue = humanFriendlyNumber(value)
    if (filters?.aggregation_axis_format) {
        switch (filters?.aggregation_axis_format) {
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
    return `${filters?.aggregation_axis_prefix || ''}${formattedValue}${filters?.aggregation_axis_postfix || ''}`
}

export const axisLabel = (chartDisplayType: ChartDisplayType | undefined): string => {
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

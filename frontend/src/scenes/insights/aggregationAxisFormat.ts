import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ChartDisplayType } from '~/types'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled'] as const
export type AggregationAxisFormat = typeof formats[number]

export const aggregationAxisFormatSelectOptions: LemonSelectOptions<AggregationAxisFormat> = [
    { key: 'numeric', label: 'None' },
    { key: 'duration', label: 'Duration (s)' },
    { key: 'duration_ms', label: 'Duration (ms)' },
    { key: 'percentage', label: 'Percent (0-100)' },
    { key: 'percentage_scaled', label: 'Percent (0-1)' },
]

export const formatAggregationAxisValue = (
    axisFormat: AggregationAxisFormat | undefined,
    value: number | string
): string => {
    value = Number(value)
    switch (axisFormat) {
        case 'duration':
            return humanFriendlyDuration(value)
        case 'duration_ms':
            return humanFriendlyDuration(value / 1000)
        case 'percentage':
            return percentage(value / 100)
        case 'percentage_scaled':
            return percentage(value)
        case 'numeric': // numeric is default
        default:
            return humanFriendlyNumber(value)
    }
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

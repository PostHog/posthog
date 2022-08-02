import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { compactNumber, humanFriendlyDuration, percentage } from 'lib/utils'
import { ChartDisplayType } from '~/types'

const formats = ['numeric', 'duration', 'percentage'] as const
export type AggregationAxisFormat = typeof formats[number]

export const isAggregationAxisFormat = (candidate: unknown): candidate is AggregationAxisFormat =>
    formats.includes(candidate as AggregationAxisFormat)

export const aggregationAxisFormatSelectOptions = formats.reduce((target, format) => {
    target[format as string] = { label: format as string }
    return target
}, {} as LemonSelectOptions)

export const formatAggregationAxisValue = (axisFormat: AggregationAxisFormat, value: number | string): string => {
    switch (axisFormat) {
        case 'duration':
            return humanFriendlyDuration(value)
        case 'percentage':
            return percentage(Number(value) / 100)
        case 'numeric': // numeric is default
        default:
            return compactNumber(Number(value))
    }
}

export const canFormatAxis = (chartDisplayType: ChartDisplayType | undefined): boolean => {
    return (
        !!chartDisplayType &&
        [
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.ActionsLineGraphCumulative,
            ChartDisplayType.ActionsBar,
            ChartDisplayType.ActionsBarValue,
        ].includes(chartDisplayType)
    )
}

import { LemonSelectOption } from 'lib/components/LemonSelect'
import { compactNumber, humanFriendlyDuration, percentage } from 'lib/utils'
import { ChartDisplayType } from '~/types'

const formats = ['numeric', 'duration', 'percentage'] as const
export type AggregationAxisFormat = typeof formats[number]

export const aggregationAxisFormatSelectOptions: Record<AggregationAxisFormat, LemonSelectOption> = {
    numeric: {
        label: 'None',
    },
    duration: {
        label: 'Duration (s)',
    },
    percentage: {
        label: 'Percent (0-100)',
    },
}

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

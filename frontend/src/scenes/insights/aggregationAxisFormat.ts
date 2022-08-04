import { LemonSelectOption } from 'lib/components/LemonSelect'
import { compactNumber, humanFriendlyDuration, percentage } from 'lib/utils'
import { ChartDisplayType } from '~/types'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled'] as const
export type AggregationAxisFormat = typeof formats[number]

export const aggregationAxisFormatSelectOptions: Record<AggregationAxisFormat, LemonSelectOption> = {
    numeric: {
        label: 'None',
    },
    duration: {
        label: 'Duration (s)',
    },
    duration_ms: {
        label: 'Duration (ms)',
    },
    percentage: {
        label: 'Percent (0-100)',
    },
    percentage_scaled: {
        label: 'Percent (0-1)',
    },
}

export const formatAggregationAxisValue = (axisFormat: AggregationAxisFormat, value: number | string): string => {
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
            return compactNumber(value)
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

export const axisLabel = (chartDisplayType: ChartDisplayType | undefined): string => {
    switch (chartDisplayType) {
        case ChartDisplayType.ActionsLineGraph:
        case ChartDisplayType.ActionsLineGraphCumulative:
        case ChartDisplayType.ActionsBar:
            return 'Y-axis unit'
        case ChartDisplayType.ActionsBarValue:
            return 'X-axis unit'
        case ChartDisplayType.ActionsTable:
        case ChartDisplayType.ActionsPie:
        case ChartDisplayType.WorldMap:
        default:
            return 'Unit'
    }
}

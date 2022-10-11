import { LemonSelectOption } from 'lib/components/LemonSelect'
import { humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { ChartDisplayType } from '~/types'
import { currencies, isCurrency } from 'lib/components/CurrencyPicker/CurrencyPicker'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled'] as const
export type AggregationAxisFormat = typeof formats[number] | currencies

export const aggregationAxisFormatSelectOptions: LemonSelectOption<AggregationAxisFormat>[] = [
    { value: 'numeric', label: 'None' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'percentage', label: 'Percent (0-100)' },
    { value: 'percentage_scaled', label: 'Percent (0-1)' },
]

export const formatAggregationAxisValue = (
    axisFormat: AggregationAxisFormat | undefined,
    value: number | string
): string => {
    value = Number(value)

    if (axisFormat && isCurrency(axisFormat)) {
        return value.toLocaleString(window.navigator.language, {
            style: 'currency',
            currency: axisFormat,
        })
    }

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

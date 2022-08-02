import { LemonSelectOptions } from 'lib/components/LemonSelect'
import { compactNumber, humanFriendlyDuration } from 'lib/utils'

const formats = ['numeric', 'duration', 'percentage'] as const
export type YAxisFormat = typeof formats[number]

export const isYAxisFormat = (candidate: unknown): candidate is YAxisFormat => {
    return formats.includes(candidate as YAxisFormat)
}

export const yAxisFormatSelectOptions = formats.reduce((target, format) => {
    target[format as string] = { label: format as string }
    return target
}, {} as LemonSelectOptions)

function toPercentage(value: number | string): string {
    const numVal = Number(value)
    const fixedValue = numVal < 1 ? numVal.toFixed(2) : numVal.toFixed(0)
    return `${fixedValue}%`
}

export function formatYAxisValue(yAxisFormat: YAxisFormat, value: number | string): string {
    switch (yAxisFormat) {
        case 'duration':
            return humanFriendlyDuration(value)
        case 'percentage':
            return toPercentage(value)
        case 'numeric': // numeric is default
        default:
            return compactNumber(Number(value))
    }
}

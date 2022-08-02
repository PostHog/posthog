import { LemonSelectOptions } from 'lib/components/LemonSelect'

const formats = ['numeric', 'duration', 'percentage'] as const
export type YAxisFormat = typeof formats[number]

export const isYAxisFormat = (candidate: unknown): candidate is YAxisFormat => {
    return formats.includes(candidate as YAxisFormat)
}

export const yAxisFormatSelectOptions = formats.reduce((target, format) => {
    target[format as string] = { label: format as string }
    return target
}, {} as LemonSelectOptions)

const formats = ['numeric', 'duration', 'percentage'] as const
export type YAxisFormat = typeof formats[number]

export const isYAxisFormat = (candidate: unknown): candidate is YAxisFormat => {
    return formats.includes(candidate as YAxisFormat)
}

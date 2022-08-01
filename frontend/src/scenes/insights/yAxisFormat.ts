export type YAxisFormat = 'numeric' | 'duration' | 'percentage'

export const isYAxisFormat = (candidate: unknown): candidate is YAxisFormat => {
    return typeof candidate === 'string' && ['numeric', 'duration', 'percentage'].includes(candidate)
}

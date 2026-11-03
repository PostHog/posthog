import type { AccountViewTileConfig } from './accountViewTileConfig'

export const DOT_MATRIX_WEEK_OPTIONS = [4, 8, 12, 26] as const
export type DotMatrixWeeks = (typeof DOT_MATRIX_WEEK_OPTIONS)[number]
const DEFAULT_WEEKS: DotMatrixWeeks = 8

export interface DotMatrixTileConfig {
    mode: 'dots' | 'count'
    weeks: DotMatrixWeeks
    selectedSeries: string[]
}

export function getDotMatrixTileConfig(config?: AccountViewTileConfig): DotMatrixTileConfig {
    const selectedSeries = config?.selectedSeries
    const weeks = DOT_MATRIX_WEEK_OPTIONS.find((option) => option === config?.weeks) ?? DEFAULT_WEEKS
    return {
        mode: config?.mode === 'count' ? 'count' : 'dots',
        weeks,
        selectedSeries:
            Array.isArray(selectedSeries) &&
            selectedSeries.length <= 64 &&
            selectedSeries.every((key) => typeof key === 'string' && key.length > 0 && key.length <= 128)
                ? [...new Set(selectedSeries)]
                : [],
    }
}

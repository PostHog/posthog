import type { DotMatrixGroup, DotMatrixSeries } from './types'

export const DOT_MATRIX_EMPTY_GROUPS: DotMatrixGroup[] = []

export const DOT_MATRIX_SIZE_THRESHOLDS = [1, 5, 10]

export function resolveDotMatrixSeries(
    series: DotMatrixSeries[],
    groups: DotMatrixGroup[] = []
): (DotMatrixSeries & { color: string })[] {
    const groupColors = new Map(groups.map((group) => [group.key, group.color]))
    return series.map((item, index) => ({
        ...item,
        color:
            item.color ??
            (item.group !== undefined ? groupColors.get(item.group) : undefined) ??
            `var(--data-color-${(index % 15) + 1})`,
    }))
}

export function getDotMatrixActiveSeries(series: DotMatrixSeries[], values: Record<string, number>): DotMatrixSeries[] {
    return series.filter(({ key }) => Number.isFinite(values[key]) && values[key] > 0)
}

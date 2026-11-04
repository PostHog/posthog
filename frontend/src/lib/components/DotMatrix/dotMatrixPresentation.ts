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

export function getDotMatrixGroups(
    series: DotMatrixSeries[],
    groups: DotMatrixGroup[]
): (DotMatrixGroup & { series: DotMatrixSeries[] })[] {
    const byKey = new Map(series.map((item) => [item.key, item]))
    const grouped = groups.map((group) => ({
        ...group,
        series: group.items
            ? group.items.flatMap((key) => (byKey.has(key) ? [byKey.get(key)!] : []))
            : series.filter((item) => item.group === group.key),
    }))
    const assigned = new Set(grouped.flatMap((group) => group.series.map((item) => item.key)))
    const remaining = series.filter((item) => !assigned.has(item.key))
    if (remaining.length) {
        grouped.push({ key: '', label: '', series: remaining })
    }
    return grouped.filter((group) => group.series.length > 0)
}

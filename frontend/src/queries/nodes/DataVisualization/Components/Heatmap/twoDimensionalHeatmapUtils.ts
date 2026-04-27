import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import { HeatmapSortOrder, type HeatmapSettings } from '~/queries/schema/schema-general'

export const HEATMAP_ROW_LABEL_SORT_KEY = '__heatmap_row_label__'

export type HeatmapCellValues = Record<string, Record<string, number | null>>

const compareHeatmapLabels = (left: string, right: string): number =>
    left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })

const compareHeatmapValues = (
    left: number | null | undefined,
    right: number | null | undefined,
    order: Sorting['order']
): number => {
    if (left === null || left === undefined) {
        return right === null || right === undefined ? 0 : 1
    }

    if (right === null || right === undefined) {
        return -1
    }

    return (left - right) * order
}

export const sortHeatmapRows = (
    rowLabels: string[],
    cellValues: HeatmapCellValues,
    sorting: Sorting | null
): string[] => {
    if (!sorting) {
        return rowLabels
    }

    const originalIndexes = new Map(rowLabels.map((label, index) => [label, index]))

    return [...rowLabels].sort((leftLabel, rightLabel) => {
        const comparison =
            sorting.columnKey === HEATMAP_ROW_LABEL_SORT_KEY
                ? compareHeatmapLabels(leftLabel, rightLabel)
                : compareHeatmapValues(
                      cellValues[leftLabel]?.[sorting.columnKey],
                      cellValues[rightLabel]?.[sorting.columnKey],
                      sorting.order
                  )

        if (comparison !== 0) {
            return sorting.columnKey === HEATMAP_ROW_LABEL_SORT_KEY ? comparison * sorting.order : comparison
        }

        return (originalIndexes.get(leftLabel) ?? 0) - (originalIndexes.get(rightLabel) ?? 0)
    })
}

export const getSortingFromHeatmapSettings = (
    heatmapSettings: Pick<HeatmapSettings, 'sortColumn' | 'sortOrder'>
): Sorting | null => {
    if (!heatmapSettings.sortColumn || !heatmapSettings.sortOrder) {
        return null
    }

    return {
        columnKey: heatmapSettings.sortColumn,
        order: heatmapSettings.sortOrder === HeatmapSortOrder.Asc ? 1 : -1,
    }
}

export const getHeatmapSettingsWithSorting = (
    heatmapSettings: HeatmapSettings,
    sorting: Sorting | null
): HeatmapSettings => ({
    ...heatmapSettings,
    sortColumn: sorting?.columnKey,
    sortOrder: sorting?.order === 1 ? HeatmapSortOrder.Asc : sorting?.order === -1 ? HeatmapSortOrder.Desc : undefined,
})

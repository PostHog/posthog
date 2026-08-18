import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import { HeatmapSortOrder, type HeatmapSettings } from '~/queries/schema/schema-general'

import {
    getHeatmapSettingsWithSorting,
    getSortingFromHeatmapSettings,
    HEATMAP_ROW_LABEL_SORT_KEY,
    HeatmapCellValues,
    sortHeatmapColumns,
    sortHeatmapRows,
} from './twoDimensionalHeatmapUtils'

describe('twoDimensionalHeatmapUtils', () => {
    const rowLabels = ['United States', 'Germany', 'Canada', 'France']
    const cellValues: HeatmapCellValues = {
        Canada: { Enterprise: 6, Growth: 1 },
        France: { Enterprise: 6, Growth: 8 },
        Germany: { Enterprise: 12, Growth: null },
        'United States': { Enterprise: 3, Growth: 9 },
    }

    it('sorts rows descending by the selected heatmap column and keeps null values last', () => {
        const sorting: Sorting = { columnKey: 'Growth', order: -1 }

        expect(sortHeatmapRows(rowLabels, cellValues, sorting)).toEqual([
            'United States',
            'France',
            'Canada',
            'Germany',
        ])
    })

    it('sorts rows ascending by the selected heatmap column', () => {
        const sorting: Sorting = { columnKey: 'Enterprise', order: 1 }

        expect(sortHeatmapRows(rowLabels, cellValues, sorting)).toEqual([
            'United States',
            'Canada',
            'France',
            'Germany',
        ])
    })

    it('sorts rows by row label when the row header is selected', () => {
        const sorting: Sorting = { columnKey: HEATMAP_ROW_LABEL_SORT_KEY, order: 1 }

        expect(sortHeatmapRows(rowLabels, cellValues, sorting)).toEqual([
            'Canada',
            'France',
            'Germany',
            'United States',
        ])
    })

    it('preserves original order for ties', () => {
        const sorting: Sorting = { columnKey: 'Enterprise', order: -1 }

        expect(sortHeatmapRows(rowLabels, cellValues, sorting)).toEqual([
            'Germany',
            'Canada',
            'France',
            'United States',
        ])
    })

    it('keeps the query column order when no X-axis sort is set', () => {
        const columns = ['Q4', 'Q1', 'Q3', 'Q2']

        expect(sortHeatmapColumns(columns, undefined, 'null')).toEqual(columns)
    })

    it('sorts numeric X-axis columns numerically, not lexically', () => {
        const columns = ['2', '10', '1']

        expect(sortHeatmapColumns(columns, HeatmapSortOrder.Asc, 'null')).toEqual(['1', '2', '10'])
    })

    it('sorts X-axis columns descending', () => {
        const columns = ['b', 'a', 'c']

        expect(sortHeatmapColumns(columns, HeatmapSortOrder.Desc, 'null')).toEqual(['c', 'b', 'a'])
    })

    it('pins the null column last regardless of sort direction', () => {
        const columns = ['20', 'null', '3']

        expect(sortHeatmapColumns(columns, HeatmapSortOrder.Asc, 'null')).toEqual(['3', '20', 'null'])
        expect(sortHeatmapColumns(columns, HeatmapSortOrder.Desc, 'null')).toEqual(['20', '3', 'null'])
    })

    it('hydrates sorting from persisted heatmap settings', () => {
        expect(getSortingFromHeatmapSettings({ sortColumn: 'Growth', sortOrder: HeatmapSortOrder.Desc })).toEqual({
            columnKey: 'Growth',
            order: -1,
        })
    })

    it('returns null when persisted heatmap sorting is incomplete', () => {
        expect(getSortingFromHeatmapSettings({ sortColumn: 'Growth' })).toBeNull()
        expect(getSortingFromHeatmapSettings({ sortOrder: HeatmapSortOrder.Asc })).toBeNull()
    })

    it('stores sorting back into heatmap settings', () => {
        const heatmapSettings: HeatmapSettings = { xAxisColumn: 'Region' }

        expect(
            getHeatmapSettingsWithSorting(heatmapSettings, { columnKey: HEATMAP_ROW_LABEL_SORT_KEY, order: 1 })
        ).toEqual({
            xAxisColumn: 'Region',
            sortColumn: HEATMAP_ROW_LABEL_SORT_KEY,
            sortOrder: HeatmapSortOrder.Asc,
        })
    })

    it('clears persisted sorting when sorting is removed', () => {
        const heatmapSettings: HeatmapSettings = {
            sortColumn: 'Growth',
            sortOrder: HeatmapSortOrder.Desc,
            xAxisColumn: 'Region',
        }

        expect(getHeatmapSettingsWithSorting(heatmapSettings, null)).toEqual({
            sortColumn: undefined,
            sortOrder: undefined,
            xAxisColumn: 'Region',
        })
    })
})

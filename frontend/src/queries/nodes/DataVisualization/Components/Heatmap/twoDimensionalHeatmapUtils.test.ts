import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import { HeatmapSortOrder, type HeatmapSettings } from '~/queries/schema/schema-general'

import {
    getHeatmapSettingsWithSorting,
    getSortingFromHeatmapSettings,
    HEATMAP_ROW_LABEL_SORT_KEY,
    HeatmapCellValues,
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

import { DashboardTileDisplayMode } from '~/types'

import { tileDisplayQueryOverrides } from './InsightCard'

describe('tileDisplayQueryOverrides', () => {
    // null/undefined/Chart map to no overrides, so a tile renders the chart only (existing default).
    it.each([[null], [undefined], [DashboardTileDisplayMode.Chart]])('returns no overrides for %s', (mode) => {
        expect(tileDisplayQueryOverrides(mode)).toEqual({})
    })

    it('shows the table alongside the chart for chart_and_table', () => {
        expect(tileDisplayQueryOverrides(DashboardTileDisplayMode.ChartAndTable)).toEqual({ showTable: true })
    })

    it('hides the chart and shows only the table for table', () => {
        expect(tileDisplayQueryOverrides(DashboardTileDisplayMode.Table)).toEqual({
            showResults: false,
            showTable: true,
        })
    })
})

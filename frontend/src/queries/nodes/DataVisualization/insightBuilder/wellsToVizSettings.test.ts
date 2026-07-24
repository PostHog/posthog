import { InsightBuilderConfig } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { CompiledBuilderQuery } from './compileBuilderQuery'
import { mapWellsToChartSettings } from './wellsToVizSettings'

const config: InsightBuilderConfig = {
    enabled: true,
    baseQuery: 'SELECT * FROM payments',
    rows: [{ column: 'plan' }],
    columns: [{ column: 'region' }],
    values: [{ column: 'amount', aggregation: 'sum' }],
}

const compiled: CompiledBuilderQuery = {
    sql: 'SELECT …',
    rowAliases: ['plan'],
    columnAliases: ['region'],
    valueAliases: ['sum_amount'],
}

describe('mapWellsToChartSettings', () => {
    it.each([
        ChartDisplayType.ActionsLineGraph,
        ChartDisplayType.ActionsBar,
        ChartDisplayType.ActionsAreaGraph,
        ChartDisplayType.ActionsStackedBar,
    ])('puts Columns on the x-axis and Rows as the series breakdown for %s', (display) => {
        const settings = mapWellsToChartSettings(undefined, compiled, display, config)

        expect(settings.xAxis?.column).toEqual('region')
        expect(settings.seriesBreakdownColumn).toEqual('plan')
        expect(settings.yAxis?.map((axis) => axis.column)).toEqual(['sum_amount'])
    })

    it('maps heatmap wells onto the heatmap settings', () => {
        const settings = mapWellsToChartSettings(undefined, compiled, ChartDisplayType.TwoDimensionalHeatmap, config)

        expect(settings.heatmap).toEqual(
            expect.objectContaining({ yAxisColumn: 'plan', xAxisColumn: 'region', valueColumn: 'sum_amount' })
        )
        expect(settings.seriesBreakdownColumn).toBeNull()
    })

    it('preserves per-series formatting by alias across recompiles and labels the series from the well', () => {
        const prev = {
            yAxis: [{ column: 'sum_amount', settings: { formatting: { prefix: '$' } } }],
        }
        const settings = mapWellsToChartSettings(prev, compiled, ChartDisplayType.ActionsBar, config)

        expect(settings.yAxis?.[0]).toEqual({
            column: 'sum_amount',
            settings: { formatting: { prefix: '$' }, display: { label: 'Sum of amount' } },
        })
    })
})

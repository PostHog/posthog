import { ChartDisplayType } from '~/types'

import { BuilderWells, bestDisplayForWells, isWellOverCapacity, validateWellsForDisplay } from './chartCapabilities'

const wells = (rows: number, columns: number, values: number): BuilderWells => ({
    rows: Array.from({ length: rows }, (_, i) => ({ column: `row_${i}` })),
    columns: Array.from({ length: columns }, (_, i) => ({ column: `col_${i}` })),
    values: Array.from({ length: values }, (_, i) => ({ column: `val_${i}`, aggregation: 'sum' as const })),
})

describe('chartCapabilities', () => {
    describe('validateWellsForDisplay', () => {
        it.each([
            // [display, rows, columns, values, valid]
            [ChartDisplayType.BoldNumber, 0, 0, 1, true],
            [ChartDisplayType.BoldNumber, 0, 0, 0, false],
            [ChartDisplayType.BoldNumber, 1, 0, 1, false],
            [ChartDisplayType.BoldNumber, 0, 0, 2, false],
            [ChartDisplayType.ActionsLineGraph, 1, 0, 1, true],
            [ChartDisplayType.ActionsLineGraph, 1, 0, 3, true],
            [ChartDisplayType.ActionsLineGraph, 1, 1, 1, true],
            [ChartDisplayType.ActionsLineGraph, 0, 0, 1, false],
            [ChartDisplayType.ActionsLineGraph, 2, 0, 1, false],
            [ChartDisplayType.ActionsLineGraph, 1, 2, 1, false],
            [ChartDisplayType.ActionsLineGraph, 1, 0, 0, false],
            [ChartDisplayType.ActionsBar, 1, 0, 2, true],
            [ChartDisplayType.ActionsBar, 1, 1, 1, false],
            [ChartDisplayType.ActionsStackedBar, 1, 1, 1, true],
            [ChartDisplayType.ActionsStackedBar, 1, 0, 1, false],
            [ChartDisplayType.ActionsStackedBar, 1, 1, 2, false],
            [ChartDisplayType.ActionsAreaGraph, 1, 0, 1, true],
            [ChartDisplayType.ActionsPie, 1, 0, 1, true],
            [ChartDisplayType.ActionsPie, 1, 1, 1, false],
            [ChartDisplayType.ActionsPie, 1, 0, 2, false],
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 1, 1, true],
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 0, 1, false],
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 1, 2, false],
            [ChartDisplayType.ActionsTable, 2, 1, 3, true],
            [ChartDisplayType.ActionsTable, 1, 0, 0, true],
            [ChartDisplayType.ActionsTable, 0, 0, 0, false],
            [ChartDisplayType.PivotTable, 1, 0, 1, true],
            [ChartDisplayType.PivotTable, 3, 2, 4, true],
            [ChartDisplayType.PivotTable, 0, 1, 1, false],
            [ChartDisplayType.PivotTable, 1, 0, 0, false],
        ])('%s with %i rows / %i columns / %i values → valid: %s', (display, rows, columns, values, valid) => {
            const problems = validateWellsForDisplay(wells(rows, columns, values), display)
            expect(problems.length === 0).toEqual(valid)
        })

        it('caps values at 1 when a chart has a Columns field (series split replaces the series list)', () => {
            const problems = validateWellsForDisplay(wells(1, 1, 2), ChartDisplayType.ActionsLineGraph)
            expect(problems).toEqual(['Only 1 Value works when Columns is filled'])
        })

        it('rejects display types without a registered capability', () => {
            expect(validateWellsForDisplay(wells(1, 0, 1), ChartDisplayType.WorldMap)).not.toEqual([])
        })
    })

    describe('isWellOverCapacity', () => {
        it.each([
            // [well, display, rows, columns, values, expected]
            // Adding a Columns field to charts that don't use Columns — the auto-switch trigger
            ['columns' as const, ChartDisplayType.ActionsBar, 1, 1, 1, true],
            ['columns' as const, ChartDisplayType.ActionsPie, 1, 1, 1, true],
            ['rows' as const, ChartDisplayType.BoldNumber, 1, 0, 1, true],
            // A second field where only one fits
            ['rows' as const, ChartDisplayType.ActionsLineGraph, 2, 0, 1, true],
            ['values' as const, ChartDisplayType.ActionsStackedBar, 1, 1, 2, true],
            // Line charts cap values at 1 once Columns is used
            ['values' as const, ChartDisplayType.ActionsLineGraph, 1, 1, 2, true],
            // Filling toward an unmet minimum is never over capacity — incomplete charts stay selected
            ['rows' as const, ChartDisplayType.TwoDimensionalHeatmap, 1, 0, 1, false],
            ['values' as const, ChartDisplayType.ActionsLineGraph, 1, 0, 1, false],
            ['rows' as const, ChartDisplayType.ActionsTable, 5, 0, 0, false],
            // Filters never affect chart choice
            ['filters' as const, ChartDisplayType.BoldNumber, 0, 0, 1, false],
        ])('%s added on %s with %i/%i/%i wells → %s', (well, display, rows, columns, values, expected) => {
            expect(isWellOverCapacity(well, wells(rows, columns, values), display)).toEqual(expected)
        })
    })

    describe('bestDisplayForWells', () => {
        it.each([
            // [rows, columns, values, firstRowIsDate, expected]
            [0, 0, 1, false, ChartDisplayType.BoldNumber],
            [0, 0, 2, false, ChartDisplayType.ActionsTable],
            [1, 0, 1, true, ChartDisplayType.ActionsLineGraph],
            [1, 0, 1, false, ChartDisplayType.ActionsBar],
            [1, 1, 1, false, ChartDisplayType.ActionsStackedBar],
            [1, 2, 1, false, ChartDisplayType.PivotTable],
            [1, 1, 2, false, ChartDisplayType.PivotTable],
            [2, 0, 1, false, ChartDisplayType.PivotTable],
            [2, 1, 2, false, ChartDisplayType.PivotTable],
            [1, 0, 0, false, ChartDisplayType.ActionsTable],
            [0, 0, 0, false, ChartDisplayType.ActionsTable],
        ])('%i rows / %i columns / %i values (date: %s) → %s', (rows, columns, values, firstRowIsDate, expected) => {
            expect(bestDisplayForWells(wells(rows, columns, values), { firstRowIsDate })).toEqual(expected)
        })
    })
})

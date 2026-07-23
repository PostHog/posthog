import { ChartDisplayType } from '~/types'

import {
    BuilderWells,
    bestDisplayForWells,
    effectiveWells,
    isWellEnabled,
    validateWellsForDisplay,
} from './chartCapabilities'

const wells = (rows: number, columns: number, values: number): BuilderWells => ({
    rows: Array.from({ length: rows }, (_, i) => ({ column: `row_${i}` })),
    columns: Array.from({ length: columns }, (_, i) => ({ column: `col_${i}` })),
    values: Array.from({ length: values }, (_, i) => ({ column: `val_${i}`, aggregation: 'sum' as const })),
})

describe('chartCapabilities', () => {
    describe('validateWellsForDisplay', () => {
        it.each([
            // [display, rows, columns, values, valid] — only *missing required* fields invalidate;
            // extra fields in wells the chart doesn't use are ignored (never an error)
            [ChartDisplayType.BoldNumber, 0, 0, 1, true],
            [ChartDisplayType.BoldNumber, 0, 0, 0, false], // needs a value
            [ChartDisplayType.BoldNumber, 1, 0, 1, true], // extra row ignored
            [ChartDisplayType.BoldNumber, 0, 0, 2, true], // extra value ignored
            [ChartDisplayType.ActionsLineGraph, 1, 0, 1, true],
            [ChartDisplayType.ActionsLineGraph, 1, 0, 3, true],
            [ChartDisplayType.ActionsLineGraph, 1, 1, 1, true],
            [ChartDisplayType.ActionsLineGraph, 0, 0, 1, false], // needs a row
            [ChartDisplayType.ActionsLineGraph, 2, 0, 1, true], // extra row ignored
            [ChartDisplayType.ActionsLineGraph, 1, 2, 1, true], // extra column ignored
            [ChartDisplayType.ActionsLineGraph, 1, 1, 2, true], // extra value ignored
            [ChartDisplayType.ActionsLineGraph, 1, 0, 0, false], // needs a value
            [ChartDisplayType.ActionsBar, 1, 0, 2, true],
            [ChartDisplayType.ActionsBar, 1, 1, 1, true], // column ignored (bar doesn't use it)
            [ChartDisplayType.ActionsStackedBar, 1, 1, 1, true],
            [ChartDisplayType.ActionsStackedBar, 1, 0, 1, false], // needs a column
            [ChartDisplayType.ActionsStackedBar, 1, 1, 2, true], // extra value ignored
            [ChartDisplayType.ActionsPie, 1, 0, 1, true],
            [ChartDisplayType.ActionsPie, 1, 1, 1, true], // column ignored
            [ChartDisplayType.ActionsPie, 1, 0, 2, true], // extra value ignored
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 1, 1, true],
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 0, 1, false], // needs a column
            [ChartDisplayType.ActionsTable, 1, 0, 0, true],
            [ChartDisplayType.ActionsTable, 0, 0, 0, false], // needs at least one field
        ])('%s with %i rows / %i columns / %i values → valid: %s', (display, rows, columns, values, valid) => {
            const problems = validateWellsForDisplay(wells(rows, columns, values), display)
            expect(problems.length === 0).toEqual(valid)
        })

        it('rejects display types without a registered capability', () => {
            expect(validateWellsForDisplay(wells(1, 0, 1), ChartDisplayType.WorldMap)).not.toEqual([])
        })
    })

    describe('effectiveWells', () => {
        it('drops fields the chart cannot express and truncates over-max wells', () => {
            // Bar doesn't use Columns; a column carried from another chart is dropped
            expect(effectiveWells(wells(1, 1, 1), ChartDisplayType.ActionsBar).columns).toHaveLength(0)
            // BoldNumber uses neither rows nor columns and only 1 value
            const bold = effectiveWells(wells(2, 1, 3), ChartDisplayType.BoldNumber)
            expect(bold.rows).toHaveLength(0)
            expect(bold.columns).toHaveLength(0)
            expect(bold.values).toHaveLength(1)
            // Line caps values at 1 once a column is present
            expect(effectiveWells(wells(1, 1, 3), ChartDisplayType.ActionsLineGraph).values).toHaveLength(1)
            // Line with no column keeps all its values
            expect(effectiveWells(wells(1, 0, 3), ChartDisplayType.ActionsLineGraph).values).toHaveLength(3)
        })

        it('keeps everything for the table (all wells unbounded)', () => {
            const table = effectiveWells(wells(2, 2, 2), ChartDisplayType.ActionsTable)
            expect([table.rows.length, table.columns.length, table.values.length]).toEqual([2, 2, 2])
        })
    })

    describe('isWellEnabled', () => {
        it.each([
            // [well, display, enabled] — chart type drives which wells accept fields
            ['columns' as const, ChartDisplayType.ActionsBar, false],
            ['columns' as const, ChartDisplayType.ActionsPie, false],
            ['columns' as const, ChartDisplayType.ActionsStackedBar, true],
            ['columns' as const, ChartDisplayType.ActionsLineGraph, true],
            ['rows' as const, ChartDisplayType.BoldNumber, false],
            ['values' as const, ChartDisplayType.BoldNumber, true],
            ['rows' as const, ChartDisplayType.ActionsBar, true],
            // Filters apply to every chart
            ['filters' as const, ChartDisplayType.BoldNumber, true],
            ['filters' as const, ChartDisplayType.ActionsPie, true],
        ])('%s on %s → enabled: %s', (well, display, enabled) => {
            expect(isWellEnabled(well, display)).toEqual(enabled)
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
            // Shapes no single chart can express fall back to the grouped table
            [1, 2, 1, false, ChartDisplayType.ActionsTable],
            [1, 1, 2, false, ChartDisplayType.ActionsTable],
            [2, 0, 1, false, ChartDisplayType.ActionsTable],
            [2, 1, 2, false, ChartDisplayType.ActionsTable],
            [1, 0, 0, false, ChartDisplayType.ActionsTable],
            [0, 0, 0, false, ChartDisplayType.ActionsTable],
        ])('%i rows / %i columns / %i values (date: %s) → %s', (rows, columns, values, firstRowIsDate, expected) => {
            expect(bestDisplayForWells(wells(rows, columns, values), { firstRowIsDate })).toEqual(expected)
        })
    })
})

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
            // extra fields in wells the chart doesn't use are ignored (never an error).
            // Convention: Columns = primary axis, Rows = breakdown.
            [ChartDisplayType.BoldNumber, 0, 0, 1, true],
            [ChartDisplayType.BoldNumber, 0, 0, 0, false], // needs a value
            [ChartDisplayType.BoldNumber, 1, 0, 1, true], // extra row ignored
            [ChartDisplayType.BoldNumber, 0, 0, 2, true], // extra value ignored
            [ChartDisplayType.ActionsLineGraph, 0, 1, 1, true], // 1 column (x-axis) + 1 value
            [ChartDisplayType.ActionsLineGraph, 0, 0, 1, false], // needs a column (x-axis)
            [ChartDisplayType.ActionsLineGraph, 0, 1, 0, false], // needs a value
            [ChartDisplayType.ActionsLineGraph, 1, 1, 1, true], // row breakdown allowed
            [ChartDisplayType.ActionsLineGraph, 0, 1, 3, true], // multiple values allowed
            [ChartDisplayType.ActionsBar, 0, 1, 2, true],
            [ChartDisplayType.ActionsBar, 0, 0, 1, false], // needs a column (x-axis)
            [ChartDisplayType.ActionsBar, 1, 1, 1, true], // row ignored (bar has no breakdown)
            [ChartDisplayType.ActionsStackedBar, 1, 1, 1, true],
            [ChartDisplayType.ActionsStackedBar, 0, 1, 1, false], // needs a row (stacked breakdown)
            [ChartDisplayType.ActionsStackedBar, 1, 0, 1, false], // needs a column (x-axis)
            [ChartDisplayType.ActionsPie, 0, 1, 1, true],
            [ChartDisplayType.ActionsPie, 0, 0, 1, false], // needs a column (the slices)
            [ChartDisplayType.ActionsPie, 1, 1, 1, true], // row ignored
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 1, 1, true],
            [ChartDisplayType.TwoDimensionalHeatmap, 1, 0, 1, false], // needs a column (x-axis)
            [ChartDisplayType.TwoDimensionalHeatmap, 0, 1, 1, false], // needs a row (y-axis)
            [ChartDisplayType.ActionsTable, 0, 1, 0, true], // a dimension column
            [ChartDisplayType.ActionsTable, 0, 0, 1, true], // a metric
            [ChartDisplayType.ActionsTable, 0, 0, 0, false], // needs at least one field
        ])('%s with %i rows / %i columns / %i values → valid: %s', (display, rows, columns, values, valid) => {
            const problems = validateWellsForDisplay(wells(rows, columns, values), display)
            expect(problems.length === 0).toEqual(valid)
        })

        it('rejects display types without a registered capability', () => {
            expect(validateWellsForDisplay(wells(0, 1, 1), ChartDisplayType.WorldMap)).not.toEqual([])
        })
    })

    describe('effectiveWells', () => {
        it('drops fields the chart cannot express and truncates over-max wells', () => {
            // Bar doesn't use Rows (no breakdown); a row carried from another chart is dropped
            expect(effectiveWells(wells(1, 1, 1), ChartDisplayType.ActionsBar).rows).toHaveLength(0)
            expect(effectiveWells(wells(1, 1, 1), ChartDisplayType.ActionsBar).columns).toHaveLength(1)
            // BoldNumber uses neither rows nor columns and only 1 value
            const bold = effectiveWells(wells(2, 1, 3), ChartDisplayType.BoldNumber)
            expect(bold.rows).toHaveLength(0)
            expect(bold.columns).toHaveLength(0)
            expect(bold.values).toHaveLength(1)
            // Line caps values at 1 once a Row breakdown is present
            expect(effectiveWells(wells(1, 1, 3), ChartDisplayType.ActionsLineGraph).values).toHaveLength(1)
            // Line with no breakdown keeps all its values
            expect(effectiveWells(wells(0, 1, 3), ChartDisplayType.ActionsLineGraph).values).toHaveLength(3)
        })

        it('keeps Columns + Values but drops Rows for the table', () => {
            const table = effectiveWells(wells(2, 2, 2), ChartDisplayType.ActionsTable)
            expect([table.rows.length, table.columns.length, table.values.length]).toEqual([0, 2, 2])
        })
    })

    describe('isWellEnabled', () => {
        it.each([
            // [well, display, enabled] — chart type drives which wells accept fields
            ['columns' as const, ChartDisplayType.ActionsBar, true],
            ['columns' as const, ChartDisplayType.ActionsPie, true],
            ['columns' as const, ChartDisplayType.ActionsStackedBar, true],
            ['columns' as const, ChartDisplayType.ActionsLineGraph, true],
            ['rows' as const, ChartDisplayType.BoldNumber, false],
            ['rows' as const, ChartDisplayType.ActionsBar, false], // bar has no breakdown
            ['rows' as const, ChartDisplayType.ActionsLineGraph, true],
            ['rows' as const, ChartDisplayType.ActionsStackedBar, true],
            ['rows' as const, ChartDisplayType.ActionsTable, false],
            ['values' as const, ChartDisplayType.BoldNumber, true],
            // Filters apply to every chart
            ['filters' as const, ChartDisplayType.BoldNumber, true],
            ['filters' as const, ChartDisplayType.ActionsPie, true],
        ])('%s on %s → enabled: %s', (well, display, enabled) => {
            expect(isWellEnabled(well, display)).toEqual(enabled)
        })
    })

    describe('bestDisplayForWells', () => {
        it.each([
            // [rows, columns, values, firstColumnIsDate, expected]
            [0, 0, 1, false, ChartDisplayType.BoldNumber],
            [0, 0, 2, false, ChartDisplayType.ActionsTable],
            [0, 1, 1, true, ChartDisplayType.ActionsLineGraph], // date x-axis
            [0, 1, 1, false, ChartDisplayType.ActionsBar],
            [1, 1, 1, false, ChartDisplayType.ActionsStackedBar], // column x-axis + row breakdown
            [0, 2, 1, false, ChartDisplayType.ActionsTable],
            [1, 1, 2, false, ChartDisplayType.ActionsTable],
            [2, 0, 1, false, ChartDisplayType.ActionsTable],
            [1, 0, 0, false, ChartDisplayType.ActionsTable],
            [0, 0, 0, false, ChartDisplayType.ActionsTable],
        ])('%i rows / %i columns / %i values (date: %s) → %s', (rows, columns, values, firstColumnIsDate, expected) => {
            expect(bestDisplayForWells(wells(rows, columns, values), { firstColumnIsDate })).toEqual(expected)
        })
    })
})

import { buildScatterData, describeSkippedRows } from './scatterUtils'

describe('buildScatterData', () => {
    const columnIndexes = { org: 0, gb_ingested: 1, query_count: 2 }
    const settings = { xAxisColumn: 'gb_ingested', yAxisColumn: 'query_count', labelColumn: 'org' }

    it('builds one labeled point per row', () => {
        const { points, skippedRowCount } = buildScatterData(
            [
                ['Org A', 10, 100],
                ['Org B', 20, 200],
            ],
            settings,
            columnIndexes
        )

        expect(points).toEqual([
            { x: 10, y: 100, label: 'Org A', xDisplay: '10', yDisplay: '100' },
            { x: 20, y: 200, label: 'Org B', xDisplay: '20', yDisplay: '200' },
        ])
        expect(skippedRowCount).toBe(0)
    })

    it('coerces numeric strings to numbers', () => {
        const { points } = buildScatterData([['Org A', '10.5', '100']], settings, columnIndexes)

        expect(points).toEqual([{ x: 10.5, y: 100, label: 'Org A', xDisplay: '10.5', yDisplay: '100' }])
    })

    it('keeps exact digits for integers beyond the JS safe-integer range', () => {
        // Int64/UInt64 aggregates arrive as numeric strings; Number() would round them
        const { points } = buildScatterData([['Org A', '9007199254740993', 100]], settings, columnIndexes)

        expect(points[0].xDisplay).toBe('9007199254740993')
        expect(points[0].yDisplay).toBe('100')
    })

    test.each([
        ['null x', [['Org A', null, 100]]],
        ['null y', [['Org A', 10, null]]],
        ['non-numeric x', [['Org A', 'not a number', 100]]],
        ['empty-string y', [['Org A', 10, '']]],
        ['whitespace-string x', [['Org A', '  ', 100]]],
        ['infinite y', [['Org A', 10, 'Infinity']]],
    ])('skips and counts rows with %s', (_name, rows) => {
        const { points, skippedRowCount } = buildScatterData(rows, settings, columnIndexes)

        expect(points).toEqual([])
        expect(skippedRowCount).toBe(1)
    })

    it('skips non-positive values on a logarithmic axis and keeps them on a linear one', () => {
        const rows = [
            ['Org A', 0, 100],
            ['Org B', -5, 200],
            ['Org C', 10, 300],
        ]

        const linear = buildScatterData(rows, settings, columnIndexes)
        expect(linear.points).toHaveLength(3)
        expect(linear.skippedRowCount).toBe(0)

        const log = buildScatterData(rows, { ...settings, xLogScale: true }, columnIndexes)
        expect(log.points).toEqual([{ x: 10, y: 300, label: 'Org C', xDisplay: '10', yDisplay: '300' }])
        expect(log.skippedRowCount).toBe(2)
    })

    it('returns no points when a selected column is missing from the response', () => {
        const { points, skippedRowCount } = buildScatterData(
            [['Org A', 10, 100]],
            { ...settings, xAxisColumn: 'gone' },
            columnIndexes
        )

        expect(points).toEqual([])
        expect(skippedRowCount).toBe(0)
    })

    it('leaves labels null when no label column is selected', () => {
        const { points } = buildScatterData(
            [['Org A', 10, 100]],
            { ...settings, labelColumn: undefined },
            columnIndexes
        )

        expect(points).toEqual([{ x: 10, y: 100, label: null, xDisplay: '10', yDisplay: '100' }])
    })
})

describe('describeSkippedRows', () => {
    test.each([
        [0, false, ''],
        [1, false, '1 row was skipped because the X or Y value is missing or not numeric.'],
        [2, false, '2 rows were skipped because the X or Y value is missing or not numeric.'],
        [
            2,
            true,
            '2 rows were skipped because the X or Y value is missing or not numeric, or not positive on a logarithmic scale.',
        ],
    ])('describes %d skipped rows (log scale: %s)', (count, hasLogScale, expected) => {
        expect(describeSkippedRows(count, hasLogScale)).toBe(expected)
    })
})

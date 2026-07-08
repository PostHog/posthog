import { flintChartInput } from './flintChartInput'

describe('flintChartInput', () => {
    const dateColumns = ['day', 'signups']
    const dateTypes = ['Date', 'UInt64']
    const dateRows = [
        ['2026-01-01', 10],
        ['2026-01-02', 20],
    ]

    it('returns null without columns or rows so the pane can show an empty state', () => {
        expect(flintChartInput({ columns: [], columnTypes: [], rows: [] })).toBeNull()
        expect(flintChartInput({ columns: dateColumns, columnTypes: dateTypes, rows: [] })).toBeNull()
    })

    it('infers a line chart with temporal x from ClickHouse column types', () => {
        const input = flintChartInput({ columns: dateColumns, columnTypes: dateTypes, rows: dateRows })

        expect(input?.chart_spec.chartType).toBe('Line Chart')
        expect(input?.chart_spec.encodings).toEqual({ x: { field: 'day' }, y: { field: 'signups' } })
        expect(input?.semantic_types).toEqual({ day: 'Date', signups: 'Quantity' })
        expect(input?.data.values).toEqual([
            { day: '2026-01-01', signups: 10 },
            { day: '2026-01-02', signups: 20 },
        ])
    })

    it('falls back to value sniffing when column types are missing', () => {
        const input = flintChartInput({ columns: dateColumns, columnTypes: [null, null], rows: dateRows })

        expect(input?.semantic_types).toEqual({ day: 'Date', signups: 'Quantity' })
        expect(input?.chart_spec.chartType).toBe('Line Chart')
    })

    it('routes a leftover categorical column onto the color channel', () => {
        const input = flintChartInput({
            columns: ['day', 'plan', 'signups'],
            columnTypes: ['Date', 'String', 'UInt64'],
            rows: [['2026-01-01', 'free', 10]],
        })

        expect(input?.chart_spec.encodings).toEqual({
            x: { field: 'day' },
            y: { field: 'signups' },
            color: { field: 'plan' },
        })
    })

    it('folds multiple numeric columns into static series', () => {
        const input = flintChartInput({
            columns: ['day', 'signups', 'churns'],
            columnTypes: ['Date', 'UInt64', 'UInt64'],
            rows: [['2026-01-01', 10, 2]],
        })

        expect(input?.chart_spec.encodings).toEqual({
            x: { field: 'day' },
            y: [{ field: 'signups' }, { field: 'churns' }],
        })
    })

    it('charts row counts when there is no numeric column', () => {
        const input = flintChartInput({
            columns: ['plan'],
            columnTypes: ['String'],
            rows: [['free'], ['free'], ['paid']],
        })

        expect(input?.chart_spec.chartType).toBe('Bar Chart')
        expect(input?.chart_spec.encodings).toEqual({ x: { field: 'plan' }, y: { aggregate: 'count' } })
    })

    it('remaps encodings onto color/size when overridden to a pie chart', () => {
        const input = flintChartInput({
            columns: ['plan', 'signups'],
            columnTypes: ['String', 'UInt64'],
            rows: [['free', 10]],
            chartType: 'Doughnut Chart',
        })

        expect(input?.chart_spec.chartType).toBe('Doughnut Chart')
        expect(input?.chart_spec.encodings).toEqual({ color: { field: 'plan' }, size: { field: 'signups' } })
    })
})

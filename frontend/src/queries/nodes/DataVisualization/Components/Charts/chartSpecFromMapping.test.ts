import { type ChartSpecMapping, chartSpecFromMapping } from './chartSpecFromMapping'

describe('chartSpecFromMapping', () => {
    const columns = ['day', 'revenue', 'conversion']
    const rows: unknown[][] = [
        ['2026-01-01', 100, 0.1],
        ['2026-01-02', 200, 0.2],
    ]

    it('builds an inline ChartSpec from a column mapping and real rows', () => {
        const mapping: ChartSpecMapping = {
            chartType: 'combo',
            title: 'Revenue vs conversion',
            xColumn: 'day',
            series: [
                { column: 'revenue', label: 'Revenue', type: 'bar', axis: 'left' },
                { column: 'conversion', type: 'line', axis: 'right' },
            ],
            axes: [
                { id: 'left', format: 'currency' },
                { id: 'right', format: 'percentage_scaled' },
            ],
        }

        const spec = chartSpecFromMapping(mapping, columns, rows)

        expect(spec).not.toBeNull()
        expect(spec?.labels).toEqual(['2026-01-01', '2026-01-02'])
        expect(spec?.series).toEqual([
            { key: 'revenue', label: 'Revenue', data: [100, 200], type: 'bar', axis: 'left' },
            { key: 'conversion', label: 'conversion', data: [0.1, 0.2], type: 'line', axis: 'right' },
        ])
        expect(spec?.axes).toHaveLength(2)
    })

    it('coerces non-numeric and null cells to 0', () => {
        const mapping: ChartSpecMapping = {
            chartType: 'bar',
            xColumn: 'day',
            series: [{ column: 'revenue' }],
        }
        const spec = chartSpecFromMapping(mapping, columns, [
            ['a', null],
            ['b', 'nope'],
        ])
        expect(spec?.series[0].data).toEqual([0, 0])
    })

    it('returns null when the x column is missing', () => {
        const mapping: ChartSpecMapping = { chartType: 'bar', xColumn: 'missing', series: [{ column: 'revenue' }] }
        expect(chartSpecFromMapping(mapping, columns, rows)).toBeNull()
    })

    it('returns null when no mapped series column exists', () => {
        const mapping: ChartSpecMapping = { chartType: 'bar', xColumn: 'day', series: [{ column: 'nope' }] }
        expect(chartSpecFromMapping(mapping, columns, rows)).toBeNull()
    })
})

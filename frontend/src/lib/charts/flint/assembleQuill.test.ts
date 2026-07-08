import type { ChartAssemblyInput } from 'flint-chart/core'

import { assembleQuill } from './assembleQuill'
import type { QuillBarChartSpec, QuillLineChartSpec, QuillPieChartSpec } from './types'

const SALES_ROWS = [
    { region: 'North', product: 'Widget', revenue: 100 },
    { region: 'South', product: 'Widget', revenue: 200 },
    { region: 'North', product: 'Gadget', revenue: 300 },
    { region: 'South', product: 'Gadget', revenue: 400 },
]

function barInput(chartType: string, overrides?: Partial<ChartAssemblyInput['chart_spec']>): ChartAssemblyInput {
    return {
        data: { values: SALES_ROWS },
        semantic_types: { region: 'Category', product: 'Category', revenue: 'Price' },
        chart_spec: {
            chartType,
            encodings: { x: { field: 'region' }, y: { field: 'revenue' }, color: { field: 'product' } },
            ...overrides,
        },
    }
}

describe('assembleQuill', () => {
    it('throws on chart types the quill backend has no template for', () => {
        expect(() => assembleQuill(barInput('Scatter Plot'))).toThrow(/Unknown quill chart type: Scatter Plot/)
    })

    test.each([
        ['Bar Chart', 'grouped'],
        ['Grouped Bar Chart', 'grouped'],
        ['Stacked Bar Chart', 'stacked'],
    ])('%s pivots long-form rows into category-aligned quill series with barLayout %s', (chartType, barLayout) => {
        const spec = assembleQuill(barInput(chartType)) as QuillBarChartSpec

        expect(spec.component).toBe('BarChart')
        expect(spec.labels).toEqual(['North', 'South'])
        expect(spec.config.barLayout).toBe(barLayout)
        expect(spec.config.axisOrientation).toBe('vertical')
        // One series per color-channel value, data aligned to the label order
        expect(spec.series).toEqual([
            expect.objectContaining({ key: 'Widget', data: [100, 200] }),
            expect.objectContaining({ key: 'Gadget', data: [300, 400] }),
        ])
        expect(spec.config.legend?.show).toBe(true)
    })

    it('renders horizontal bars when the category sits on the y channel', () => {
        const input = barInput('Bar Chart')
        input.chart_spec.encodings = { y: { field: 'region' }, x: { field: 'revenue' } }
        const spec = assembleQuill(input) as QuillBarChartSpec

        expect(spec.config.axisOrientation).toBe('horizontal')
        expect(spec.labels).toEqual(['North', 'South'])
        expect(spec.series).toHaveLength(1)
        expect(spec.series[0].data).toEqual([400, 600])
        expect(spec.config.legend?.show).toBe(false)
    })

    it('sorts temporal x values chronologically even when rows arrive out of order', () => {
        const spec = assembleQuill({
            data: {
                values: [
                    { day: '2026-03-01', signups: 30 },
                    { day: '2026-01-01', signups: 10 },
                    { day: '2026-02-01', signups: 20 },
                ],
            },
            semantic_types: { day: 'Date', signups: 'Quantity' },
            chart_spec: {
                chartType: 'Line Chart',
                encodings: { x: { field: 'day' }, y: { field: 'signups' } },
            },
        }) as QuillLineChartSpec

        expect(spec.component).toBe('LineChart')
        expect(spec.series[0].data).toEqual([10, 20, 30])
        expect(spec.labels).toHaveLength(3)
        expect(spec.series[0].fill).toBeUndefined()
    })

    it('Area Chart emits filled series so quill stacks them', () => {
        const spec = assembleQuill(barInput('Area Chart')) as QuillLineChartSpec

        expect(spec.component).toBe('LineChart')
        expect(spec.series).toHaveLength(2)
        for (const s of spec.series) {
            expect(s.fill).toEqual({ opacity: 0.4 })
        }
    })

    test.each([
        ['Pie Chart', 0],
        ['Doughnut Chart', 0.5],
    ])('%s sums the size measure per color category (innerRadiusRatio %d)', (chartType, innerRadiusRatio) => {
        const spec = assembleQuill({
            data: { values: SALES_ROWS },
            semantic_types: { product: 'Category', revenue: 'Price' },
            chart_spec: {
                chartType,
                encodings: { color: { field: 'product' }, size: { field: 'revenue' } },
            },
        }) as QuillPieChartSpec

        expect(spec.component).toBe('PieChart')
        expect(spec.config.innerRadiusRatio).toBe(innerRadiusRatio)
        expect(spec.series).toEqual([
            expect.objectContaining({ label: 'Widget', data: [300] }),
            expect.objectContaining({ label: 'Gadget', data: [700] }),
        ])
    })

    it('derives _count from an aggregate encoding and charts row counts', () => {
        const spec = assembleQuill({
            data: {
                values: [
                    { plan: 'free', user: 'a' },
                    { plan: 'free', user: 'b' },
                    { plan: 'paid', user: 'c' },
                ],
            },
            semantic_types: { plan: 'Category' },
            chart_spec: {
                chartType: 'Bar Chart',
                encodings: { x: { field: 'plan' }, y: { aggregate: 'count' } },
            },
        }) as QuillBarChartSpec

        expect(spec.labels).toEqual(['free', 'paid'])
        expect(spec.series[0].data).toEqual([2, 1])
    })

    it('ignores facet channels with a warning instead of failing', () => {
        const input = barInput('Bar Chart')
        input.chart_spec.encodings = { ...input.chart_spec.encodings, column: { field: 'product' } }
        const spec = assembleQuill(input)

        expect(spec.component).toBe('BarChart')
        expect(spec._warnings).toEqual([expect.objectContaining({ code: 'facet-unsupported', channel: 'column' })])
    })
})

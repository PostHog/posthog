import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'

import { columnsFromResponse } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { ChartDisplayType } from '~/types'

import type { DecideResponseApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { buildChartDecision, readChartDecision } from './chartRecommendation'

const columns = columnsFromResponse({
    columns: ['day', 'region', 'revenue', 'orders'],
    types: [
        ['day', 'Date'],
        ['region', 'String'],
        ['revenue', 'Float64'],
        ['orders', 'Int64'],
    ],
})
const rows = [
    ['2026-01-01', 'North', 12, 3],
    ['2026-01-02', 'South', 20, 5],
]
function answer(choices: Record<string, string>): DecideResponseApi {
    return {
        model: 'test',
        input_tokens: 1,
        latency_ms: 1,
        answers: Object.fromEntries(
            Object.entries(choices).map(([id, choice]) => [
                id,
                { type: 'choice', choice, confidence: 1, probabilities: {}, probability: null, score: null },
            ])
        ),
    }
}

describe('SQL chart recommendations', () => {
    it('bounds the prompt and falls back for empty, wide, or ambiguous results', () => {
        const request = buildChartDecision(
            columns,
            Array.from({ length: 200 }, () => ['2026-01-01', 'x'.repeat(10000), 1, 2])
        )!
        expect(request.state.length).toBeLessThan(2000)
        expect(JSON.parse(request.state).sample).toHaveLength(3)
        expect(buildChartDecision(columns, [])).toBeNull()
        expect(
            buildChartDecision(
                Array.from({ length: 16 }, (_, i) => ({ ...columns[0], name: `c${i}` })),
                rows
            )
        ).toBeNull()
        expect(buildChartDecision([columns[0], columns[0]], rows)).toBeNull()
        const schemaRequest = buildChartDecision(columns, undefined, 'x'.repeat(10000))!
        expect(JSON.parse(schemaRequest.state)).toMatchObject({ schema_only: true, row_count: null })
        expect(JSON.parse(schemaRequest.state).query).toHaveLength(4000)
        expect(JSON.parse(schemaRequest.state).sample).toBeUndefined()
    })

    it.each(Object.values(OutputTab))('binds a temporal chart and selects %s', (layout) => {
        const result = readChartDecision(
            answer({ chart: ChartDisplayType.ActionsLineGraph, layout, x: 'c0', dimension: 'c1', value: 'c2' }),
            columns,
            rows
        )!
        expect(result.outputTab).toBe(layout === OutputTab.Results ? OutputTab.Visualization : layout)
        expect(result.display).toBe(ChartDisplayType.ActionsLineGraph)
        expect(result.chartSettings).toEqual({
            xAxis: { column: 'day' },
            yAxis: [{ column: 'revenue' }],
            seriesBreakdownColumn: 'region',
        })
    })

    it.each([
        {
            name: 'single integer',
            types: ['Int64'],
            rows: [[1]],
            chart: ChartDisplayType.BoldNumber,
            x: 'none',
            value: 'c0',
        },
        {
            name: 'single decimal',
            types: ['Float64'],
            rows: [[12.5]],
            chart: ChartDisplayType.BoldNumber,
            x: 'none',
            value: 'c0',
        },
        {
            name: 'single zero',
            types: ['UInt8'],
            rows: [[0]],
            chart: ChartDisplayType.BoldNumber,
            x: 'none',
            value: 'c0',
        },
        {
            name: 'text records',
            types: ['String'],
            rows: [['hello'], ['world']],
            chart: ChartDisplayType.ActionsTable,
            x: 'none',
            value: 'none',
        },
        {
            name: 'category comparison',
            types: ['String', 'Int64'],
            rows: [
                ['Books', 12],
                ['Games', 20],
            ],
            chart: ChartDisplayType.ActionsBar,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'numeric relationship',
            types: ['Float64', 'Float64'],
            rows: [
                [1.5, 2.5],
                [2.5, 3.5],
            ],
            chart: ChartDisplayType.ScatterPlot,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'part to whole',
            types: ['String', 'Int64'],
            rows: [
                ['Books', 12],
                ['Games', 20],
            ],
            chart: ChartDisplayType.ActionsPie,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'part to whole with total',
            types: ['String', 'Int64'],
            rows: [
                ['Books', 12],
                ['Games', 20],
            ],
            chart: ChartDisplayType.ActionsDonut,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'volume over time',
            types: ['DateTime', 'Float64'],
            rows: [
                ['2026-01-01', 12],
                ['2026-01-02', 20],
            ],
            chart: ChartDisplayType.ActionsAreaGraph,
            x: 'c0',
            value: 'c1',
        },
    ])('renders $name with its supported chart and axes', ({ types, rows, chart, x, value }) => {
        const fields = columnsFromResponse({
            columns: types.map((_, i) => `field${i}`),
            types: types.map((type, i) => [`field${i}`, type]),
        })
        const result = readChartDecision(
            answer({ chart, layout: OutputTab.Visualization, x, value, dimension: 'none' }),
            fields,
            rows
        )!
        expect(result.display).toBe(chart)
        expect(result.outputTab).toBe(
            chart === ChartDisplayType.ActionsTable ? OutputTab.Results : OutputTab.Visualization
        )
        if (chart !== ChartDisplayType.ActionsTable) {
            expect(result.chartSettings.yAxis).toEqual([{ column: value === 'c0' ? 'field0' : 'field1' }])
            expect(result.chartSettings.xAxis).toEqual(x === 'none' ? undefined : { column: 'field0' })
        }
    })

    it('keeps a headline number visible even when the layout answer requests a table', () => {
        const fields = columnsFromResponse({ columns: ['total'], types: [['total', 'Int64']] })
        expect(
            readChartDecision(
                answer({ chart: ChartDisplayType.BoldNumber, layout: OutputTab.Results, value: 'c0', x: 'none' }),
                fields,
                [[1]]
            )
        ).toMatchObject({ display: ChartDisplayType.BoldNumber, outputTab: OutputTab.Visualization })
        const request = buildChartDecision(fields, [[1]])!
        expect(request.questions.layout.criteria).not.toHaveProperty(OutputTab.Results)
    })

    it('does not ask a single-option measure question for text-only results', () => {
        const fields = columnsFromResponse({ columns: ['message'], types: [['message', 'String']] })
        const request = buildChartDecision(fields, [['hello']])!
        expect(request.questions.value).toBeUndefined()
        expect(
            readChartDecision(
                answer({ chart: ChartDisplayType.ActionsTable, layout: OutputTab.Visualization }),
                fields,
                [['hello']]
            )
        ).toMatchObject({ display: ChartDisplayType.ActionsTable, outputTab: OutputTab.Results })
    })

    it('uses the other numeric measure when independent scatter answers select the same axis', () => {
        const fields = columnsFromResponse({
            columns: ['height', 'weight'],
            types: [
                ['height', 'Float64'],
                ['weight', 'Float64'],
            ],
        })
        expect(
            readChartDecision(
                answer({ chart: ChartDisplayType.ScatterPlot, layout: OutputTab.Both, x: 'c0', value: 'c0' }),
                fields,
                [
                    [160, 60],
                    [180, 80],
                ]
            )
        ).toMatchObject({ chartSettings: { xAxis: { column: 'height' }, yAxis: [{ column: 'weight' }] } })
    })

    it.each([
        {
            name: 'multiple scalar rows',
            types: ['Int64'],
            rows: [[1], [2]],
            chart: ChartDisplayType.BoldNumber,
            x: 'none',
            value: 'c0',
        },
        {
            name: 'text scalar',
            types: ['String'],
            rows: [['hello']],
            chart: ChartDisplayType.BoldNumber,
            x: 'none',
            value: 'c0',
        },
        {
            name: 'category on a time axis',
            types: ['String', 'Int64'],
            rows: [['Books', 12]],
            chart: ChartDisplayType.ActionsLineGraph,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'category on a scatter axis',
            types: ['String', 'Int64'],
            rows: [['Books', 12]],
            chart: ChartDisplayType.ScatterPlot,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'negative pie values',
            types: ['String', 'Int64'],
            rows: [['Books', -12]],
            chart: ChartDisplayType.ActionsPie,
            x: 'c0',
            value: 'c1',
        },
        {
            name: 'too many pie categories',
            types: ['String', 'Int64'],
            rows: Array.from({ length: 13 }, (_, i) => [`category${i}`, i]),
            chart: ChartDisplayType.ActionsDonut,
            x: 'c0',
            value: 'c1',
        },
    ])('rejects $name', ({ types, rows, chart, x, value }) => {
        const fields = columnsFromResponse({
            columns: types.map((_, i) => `field${i}`),
            types: types.map((type, i) => [`field${i}`, type]),
        })
        expect(readChartDecision(answer({ chart, layout: OutputTab.Visualization, x, value }), fields, rows)).toBeNull()
    })

    it('binds both heatmap dimensions and the color measure', () => {
        const result = readChartDecision(
            answer({
                chart: ChartDisplayType.TwoDimensionalHeatmap,
                layout: OutputTab.Both,
                x: 'c0',
                dimension: 'c1',
                value: 'c2',
            }),
            columns,
            rows
        )!
        expect(result.chartSettings.heatmap).toEqual({
            xAxisColumn: 'day',
            yAxisColumn: 'region',
            valueColumn: 'revenue',
        })
    })

    it.each([
        { chart: 'invented' },
        { x: 'missing' },
        { value: 'c1' },
        { x: 'c2' },
        { chart: ChartDisplayType.ScatterPlot },
        { chart: ChartDisplayType.BoldNumber },
        { chart: ChartDisplayType.TwoDimensionalHeatmap, dimension: 'c0' },
        { layout: 'invented' },
    ])('rejects unrenderable bindings: %j', (override) => {
        expect(
            readChartDecision(
                answer({
                    chart: ChartDisplayType.ActionsLineGraph,
                    layout: OutputTab.Both,
                    x: 'c0',
                    dimension: 'c1',
                    value: 'c2',
                    ...override,
                }),
                columns,
                rows
            )
        ).toBeNull()
    })
})

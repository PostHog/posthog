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
        expect(result.outputTab).toBe(layout)
        if (layout === OutputTab.Results) {
            expect(result.display).toBe(ChartDisplayType.ActionsTable)
        } else {
            expect(result.chartSettings).toEqual({
                xAxis: { column: 'day' },
                yAxis: [{ column: 'revenue' }],
                seriesBreakdownColumn: 'region',
            })
        }
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

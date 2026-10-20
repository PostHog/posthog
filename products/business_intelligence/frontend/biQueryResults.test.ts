import { BIConfig, BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIQuery, DEFAULT_BI_CONFIG, getBIResultDimensions } from './biEditorTypes'
import { getBIResultSummary, getBIVisualizationResponse, getBIVisualizationSource } from './biQueryResults'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'example_orders' },
})
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'example_orders' },
    rows: [field('region')],
    columns: [field('category')],
    values: [{ field: { ...field('revenue'), type: 'float' }, aggregation: 'sum' }],
    chartType: ChartDisplayType.ActionsBar,
}
const node = (config: BIConfig): BIVisualizationNode => ({
    ...buildBIQuery(config)!.node,
    kind: NodeKind.BIVisualizationNode,
    config,
})

describe('BI visualization data reuse', () => {
    test.each([
        ChartDisplayType.ActionsTable,
        ChartDisplayType.ScatterPlot,
        ChartDisplayType.ActionsLineGraph,
        ChartDisplayType.ActionsBarValue,
        ChartDisplayType.ActionsAreaGraph,
        ChartDisplayType.ActionsStackedBar,
    ])('reuses grouped data for %s and retains the expected column names', (chartType) => {
        const bar = node(config)
        const query = node({ ...config, chartType })
        expect(getBIVisualizationSource(query)).toEqual(getBIVisualizationSource(bar))
        const columns = [...getBIResultDimensions(config).map(({ column }) => column), 'sum_revenue']
        const response: HogQLQueryResponse = {
            columns,
            types: columns.map((column, index) => [column, index < 2 ? 'String' : 'Float64']),
            results: [
                ['east', 'books', 12],
                ['west', 'games', 19],
            ],
        }
        const visible = getBIVisualizationResponse(query, response) as HogQLQueryResponse
        const expected = [...getBIResultDimensions(query.config).map(({ column }) => column), 'sum_revenue']
        expect(visible.columns).toEqual(expected)
        expect(visible.types?.map(([column]) => column)).toEqual(expected)
        expect(visible.results).toEqual(response.results)
        expect(response.columns).toEqual(columns)
        expect(getBIResultSummary(query, visible)).toMatchObject({ groups: 2, marks: 2 })
        // Cached responses from before data-request normalization already use the display's columns.
        expect((getBIVisualizationResponse(query, visible) as HogQLQueryResponse).columns).toEqual(expected)
        const cached: HogQLQueryResponse = {
            ...response,
            columns: ['region', 'category', 'sum_revenue'],
            types: [
                ['region', 'String'],
                ['category', 'String'],
                ['sum_revenue', 'Float64'],
            ],
        }
        expect((getBIVisualizationResponse(query, cached) as HogQLQueryResponse).columns).toEqual(expected)
    })

    it('keeps data changes and pivot queries distinct, and preserves source execution options', () => {
        const query = node(config)
        const source = getBIVisualizationSource(query)
        expect(
            getBIVisualizationSource(node({ ...config, chartType: ChartDisplayType.TwoDimensionalHeatmap }))
        ).not.toEqual(source)
        expect(
            getBIVisualizationSource(
                node({ ...config, filters: [{ field: config.rows[0], operator: 'equals', value: 'east' }] })
            )
        ).not.toEqual(source)
        expect(getBIVisualizationSource(node({ ...config, limit: 10000 }))).not.toEqual(source)
        query.source.connectionId = 'example-connection'
        query.source.variables = { example: { variableId: 'example', code_name: 'threshold', value: 3 } }
        expect(getBIVisualizationSource(query)).toMatchObject({
            connectionId: 'example-connection',
            variables: query.source.variables,
        })
    })
})

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, FunnelVizType, InsightModel } from '~/types'

import { visualizationShape } from './visualizationShape'

describe('visualizationShape', () => {
    const dataVisualization = (display?: ChartDisplayType): InsightModel['query'] =>
        ({ kind: NodeKind.DataVisualizationNode, display }) as InsightModel['query']

    const insightVisualization = (source: object): InsightModel['query'] =>
        ({ kind: NodeKind.InsightVizNode, source }) as InsightModel['query']

    test.each([
        ['data table', { kind: NodeKind.DataTableNode }, 'table'],
        ['SQL default', dataVisualization(), 'table'],
        ['SQL bars', dataVisualization(ChartDisplayType.ActionsBar), 'bar'],
        ['SQL pie', dataVisualization(ChartDisplayType.ActionsPie), 'pie'],
        ['SQL donut', dataVisualization(ChartDisplayType.ActionsDonut), 'donut'],
        ['SQL number', dataVisualization(ChartDisplayType.BoldNumber), 'number'],
        ['SQL heatmap', dataVisualization(ChartDisplayType.CalendarHeatmap), 'heatmap'],
        ['SQL line', dataVisualization(ChartDisplayType.ActionsLineGraph), 'line'],
        ['retention', insightVisualization({ kind: NodeKind.RetentionQuery }), 'table'],
        ['paths', insightVisualization({ kind: NodeKind.PathsQuery }), 'table'],
        ['funnel', insightVisualization({ kind: NodeKind.FunnelsQuery, series: [] }), 'funnel'],
        [
            'funnel trends',
            insightVisualization({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.Trends },
            }),
            'line',
        ],
        [
            'funnel time to convert',
            insightVisualization({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
            }),
            'table',
        ],
        [
            'trend display',
            insightVisualization({
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: { display: ChartDisplayType.ActionsBar },
            }),
            'bar',
        ],
    ] as const)('%s uses a %s skeleton', (_name, query, expected) => {
        expect(visualizationShape(query as InsightModel['query'])).toBe(expected)
    })
})

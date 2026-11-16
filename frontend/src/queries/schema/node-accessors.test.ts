import { InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, FunnelVizType } from '~/types'

import {
    getDisplay,
    queryUsesDataWarehouse,
    queryVizDefinitelyRendersToCanvas,
    queryVizRendersToCanvas,
} from './node-accessors'

describe('queryVizRendersToCanvas', () => {
    const insightViz = (source: InsightQueryNode): any => ({ kind: NodeKind.InsightVizNode, source })
    const trends = (display?: ChartDisplayType): InsightQueryNode =>
        ({ kind: NodeKind.TrendsQuery, series: [], trendsFilter: display ? { display } : {} }) as InsightQueryNode

    it.each([
        {
            name: 'HogQL data table',
            query: { kind: NodeKind.DataTableNode } as any,
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'SQL viz as chart',
            query: { kind: NodeKind.DataVisualizationNode, display: ChartDisplayType.ActionsLineGraph } as any,
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: true,
        },
        {
            name: 'SQL viz as table (no display)',
            query: { kind: NodeKind.DataVisualizationNode } as any,
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'SQL viz with auto display',
            query: { kind: NodeKind.DataVisualizationNode, display: ChartDisplayType.Auto } as any,
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'trends line chart',
            query: insightViz(trends(ChartDisplayType.ActionsLineGraph)),
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: true,
        },
        {
            name: 'trends default display',
            query: insightViz(trends()),
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: true,
        },
        {
            name: 'trends bold number',
            query: insightViz(trends(ChartDisplayType.BoldNumber)),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'trends table',
            query: insightViz(trends(ChartDisplayType.ActionsTable)),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'trends world map',
            query: insightViz(trends(ChartDisplayType.WorldMap)),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'funnel steps (default)',
            query: insightViz({ kind: NodeKind.FunnelsQuery, series: [] } as InsightQueryNode),
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: true,
        },
        {
            name: 'funnel flow (Sankey)',
            query: insightViz({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.Flow },
            } as InsightQueryNode),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'funnel time to convert (table)',
            query: insightViz({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
            } as InsightQueryNode),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'funnel trends (line chart)',
            query: insightViz({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.Trends },
            } as InsightQueryNode),
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: true,
        },
        {
            name: 'retention',
            query: insightViz({ kind: NodeKind.RetentionQuery } as InsightQueryNode),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'paths',
            query: insightViz({ kind: NodeKind.PathsQuery } as InsightQueryNode),
            expectedMayRenderToCanvas: false,
            expectedDefinitelyRendersToCanvas: false,
        },
        {
            name: 'null query',
            query: null,
            expectedMayRenderToCanvas: true,
            expectedDefinitelyRendersToCanvas: false,
        },
    ])('classifies $name', ({ query, expectedMayRenderToCanvas, expectedDefinitelyRendersToCanvas }) => {
        expect(queryVizRendersToCanvas(query)).toBe(expectedMayRenderToCanvas)
        expect(queryVizDefinitelyRendersToCanvas(query)).toBe(expectedDefinitelyRendersToCanvas)
    })
})

describe('queryUsesDataWarehouse', () => {
    it('returns true for a trends query with a data warehouse series', () => {
        expect(
            queryUsesDataWarehouse({
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.DataWarehouseNode, id: 'my_table', table_name: 'stripe.charges' }],
            } as any)
        ).toBe(true)
    })

    it('unwraps InsightVizNode to inspect its source', () => {
        expect(
            queryUsesDataWarehouse({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.DataWarehouseNode, id: 'my_table', table_name: 'stripe.charges' }],
                },
            } as any)
        ).toBe(true)
    })

    it('returns false for an events-only trends query', () => {
        expect(
            queryUsesDataWarehouse({
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            } as any)
        ).toBe(false)
    })

    it('returns false for null/undefined', () => {
        expect(queryUsesDataWarehouse(null)).toBe(false)
        expect(queryUsesDataWarehouse(undefined)).toBe(false)
    })
})

describe('getDisplay', () => {
    // ActionsStackedBar is a deprecated trends/stickiness alias of ActionsBar; the API and MCP
    // accept it, and nothing downstream of getDisplay knows how to render it.
    it.each([
        [
            'trends',
            {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: { display: ChartDisplayType.ActionsStackedBar },
            },
        ],
        [
            'stickiness',
            {
                kind: NodeKind.StickinessQuery,
                series: [],
                stickinessFilter: { display: ChartDisplayType.ActionsStackedBar },
            },
        ],
    ])('normalizes the deprecated ActionsStackedBar alias to ActionsBar for %s', (_, query) => {
        expect(getDisplay(query as InsightQueryNode)).toEqual(ChartDisplayType.ActionsBar)
    })
})

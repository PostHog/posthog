import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    canToggleLegendInInsightQuery,
    getLegendToggleText,
    isLegendEnabledInInsightQuery,
    toggleLegendInInsightQuery,
} from './legendToggle'

describe('legendToggle', () => {
    describe('canToggleLegendInInsightQuery', () => {
        it.each([
            {
                title: 'trends line graph',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                    },
                },
                expected: true,
            },
            {
                title: 'world map',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.WorldMap },
                    },
                },
                expected: false,
            },
            {
                title: 'funnels steps',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: 'steps' },
                    },
                },
                expected: false,
            },
            {
                title: 'lifecycle',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { kind: NodeKind.LifecycleQuery },
                },
                expected: true,
            },
            {
                title: 'trends table',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        trendsFilter: { display: ChartDisplayType.ActionsTable },
                    },
                },
                expected: false,
            },
            {
                title: 'non-insight-viz (SQL)',
                query: { kind: NodeKind.DataVisualizationNode },
                expected: false,
            },
        ])('returns $expected for $title', ({ query, expected }) => {
            expect(canToggleLegendInInsightQuery(query as any)).toBe(expected)
        })
    })

    describe('toggleLegendInInsightQuery', () => {
        it.each([
            {
                kind: NodeKind.TrendsQuery,
                filterKey: 'trendsFilter',
                display: ChartDisplayType.ActionsLineGraph,
            },
            {
                kind: NodeKind.StickinessQuery,
                filterKey: 'stickinessFilter',
                display: ChartDisplayType.ActionsLineGraph,
            },
            {
                kind: NodeKind.LifecycleQuery,
                filterKey: 'lifecycleFilter',
                display: undefined,
            },
        ])('sets showLegend true when unset ($kind)', ({ kind, filterKey, display }) => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind,
                    [filterKey]: display ? { display } : {},
                },
            } as any

            const next = toggleLegendInInsightQuery(query) as any
            expect(next.source[filterKey]?.showLegend).toBe(true)
        })

        it('toggles showLegend off for trends', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: true },
                },
            } as any

            const next = toggleLegendInInsightQuery(query) as InsightVizNode
            const src = next.source
            expect(src.kind).toBe(NodeKind.TrendsQuery)
            if (src.kind === NodeKind.TrendsQuery) {
                expect(src.trendsFilter?.showLegend).toBe(false)
            }
        })
    })

    describe('getLegendToggleText', () => {
        it('returns hide when legend on', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: true },
                },
            } as any

            expect(getLegendToggleText(query)).toBe('Hide legend')
            expect(isLegendEnabledInInsightQuery(query)).toBe(true)
        })

        it('returns show when legend off', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: false },
                },
            } as any

            expect(getLegendToggleText(query)).toBe('Show legend')
        })

        it('after toggling unset legend, label reads hide', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                },
            } as any

            const next = toggleLegendInInsightQuery(query)
            expect(getLegendToggleText(next)).toBe('Hide legend')
        })
    })
})

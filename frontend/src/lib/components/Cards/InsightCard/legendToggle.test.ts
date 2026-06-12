import { InsightVizNode, NodeKind } from '@posthog/query-frontend/schema/schema-general'

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
                hogChartsFunnelEnabled: false,
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
                hogChartsFunnelEnabled: false,
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
                hogChartsFunnelEnabled: false,
                expected: false,
            },
            {
                title: 'funnels historical trends with breakdown and hog charts enabled',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: 'trends' },
                        breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                    },
                },
                hogChartsFunnelEnabled: true,
                expected: true,
            },
            {
                title: 'funnels historical trends with breakdown but hog charts disabled',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: 'trends' },
                        breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                    },
                },
                hogChartsFunnelEnabled: false,
                expected: false,
            },
            {
                title: 'funnels historical trends without breakdown',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        funnelsFilter: { funnelVizType: 'trends' },
                    },
                },
                hogChartsFunnelEnabled: true,
                expected: false,
            },
            {
                title: 'lifecycle',
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { kind: NodeKind.LifecycleQuery },
                },
                hogChartsFunnelEnabled: false,
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
                hogChartsFunnelEnabled: false,
                expected: false,
            },
            {
                title: 'non-insight-viz (SQL)',
                query: { kind: NodeKind.DataVisualizationNode },
                hogChartsFunnelEnabled: false,
                expected: false,
            },
        ])('returns $expected for $title', ({ query, expected, hogChartsFunnelEnabled }) => {
            expect(canToggleLegendInInsightQuery(query as any, hogChartsFunnelEnabled)).toBe(expected)
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
            {
                kind: NodeKind.FunnelsQuery,
                filterKey: 'funnelsFilter',
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

        it('reflects toggle state for funnels historical trends when hog charts are enabled', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    funnelsFilter: { funnelVizType: 'trends' },
                    breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                },
            } as any

            expect(getLegendToggleText(query, true)).toBe('Show legend')

            const next = toggleLegendInInsightQuery(query) as any
            expect(next.source.funnelsFilter?.showLegend).toBe(true)
            expect(getLegendToggleText(next, true)).toBe('Hide legend')
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

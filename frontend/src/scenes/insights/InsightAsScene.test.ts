import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { applySceneQueryUpdate } from './InsightAsScene'

describe('applySceneQueryUpdate', () => {
    it('ignores full InsightVizNode updates without a source update flag', () => {
        const setInsightQuery = jest.fn()
        const nextQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                trendsFilter: { decimalPlaces: 2 },
            },
        }

        applySceneQueryUpdate(nextQuery, setInsightQuery, nextQuery)

        expect(setInsightQuery).not.toHaveBeenCalled()
    })

    it('applies full InsightVizNode updates when they are explicitly source updates', () => {
        const setInsightQuery = jest.fn()
        const nextQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                trendsFilter: { decimalPlaces: 2 },
            },
        }

        applySceneQueryUpdate(nextQuery, setInsightQuery, nextQuery, true)

        expect(setInsightQuery).toHaveBeenCalledWith(nextQuery)
    })

    it('ignores functional InsightVizNode updates without a source update flag', () => {
        const setInsightQuery = jest.fn()
        const currentQuery: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                trendsFilter: {},
            },
        }

        applySceneQueryUpdate(currentQuery, setInsightQuery, (query) => {
            const insightQuery = query as InsightVizNode

            return {
                ...insightQuery,
                source: {
                    ...insightQuery.source,
                    trendsFilter: { decimalPlaces: 2 },
                },
            }
        })

        expect(setInsightQuery).not.toHaveBeenCalled()
    })

    it('applies non-InsightViz source updates', () => {
        const setInsightQuery = jest.fn()
        const nextSourceQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            trendsFilter: { decimalPlaces: 2 },
        }

        applySceneQueryUpdate(null, setInsightQuery, nextSourceQuery)

        expect(setInsightQuery).toHaveBeenCalledWith({
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            trendsFilter: { decimalPlaces: 2 },
        })
    })
})

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { applySceneQueryUpdate } from './InsightAsScene'

describe('applySceneQueryUpdate', () => {
    it('applies full InsightVizNode updates', () => {
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

        expect(setInsightQuery).toHaveBeenCalledWith(nextQuery)
    })

    it('applies functional query updates for InsightVizNode queries', () => {
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

        expect(setInsightQuery).toHaveBeenCalledWith({
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                trendsFilter: { decimalPlaces: 2 },
            },
        })
    })
})

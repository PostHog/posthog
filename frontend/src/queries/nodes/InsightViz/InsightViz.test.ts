import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { buildInsightVizDataNodeLogicProps } from './InsightViz'

describe('InsightViz', () => {
    it('removes frontend-only trends filter settings before data loading', () => {
        const query = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: {
                    showLegend: true,
                    yAxis: { label: 'Revenue' },
                },
            },
        } as InsightVizNode

        const props = buildInsightVizDataNodeLogicProps({
            query,
            insightProps: {
                dashboardItemId: 'new-123',
                cachedInsight: {
                    query,
                    result: ['cached-result'],
                },
            } as InsightLogicProps<InsightVizNode>,
            vizKey: 'InsightViz.test',
        })

        expect(props.query).toEqual({
            kind: NodeKind.TrendsQuery,
            series: [],
            trendsFilter: {
                showLegend: true,
            },
        })
        expect(props.cachedResults).toEqual({
            query,
            result: ['cached-result'],
        })
    })
})

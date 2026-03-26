import { expectLogic } from 'kea-test-utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { DataNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelCorrelationResultsType, FunnelCorrelationType, InsightLogicProps, InsightType } from '~/types'

import { funnelCorrelationDetailsLogic } from './funnelCorrelationDetailsLogic'

const funnelResults = [
    {
        action_id: '$pageview',
        count: 19,
        name: '$pageview',
        order: 0,
        type: 'events',
    },
    {
        action_id: '$pageview',
        count: 7,
        name: '$pageview',
        order: 1,
        type: 'events',
    },
    {
        action_id: '$pageview',
        count: 4,
        name: '$pageview',
        order: 2,
        type: 'events',
    },
]

describe('funnelCorrelationDetailsLogic', () => {
    let logic: ReturnType<typeof funnelCorrelationDetailsLogic.build>

    beforeEach(() => {
        initKeaTests(false)
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
        cachedInsight: {
            short_id: undefined,
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.ActionsNode, id: 1 },
                        { kind: NodeKind.ActionsNode, id: 1 },
                    ],
                },
            } as InsightVizNode,
            result: funnelResults,
        },
    }

    beforeEach(async () => {
        const builtDataNodeLogic = dataNodeLogic({
            key: insightVizDataNodeKey(defaultProps),
            query: {} as DataNode,
            cachedResults: {
                result: funnelResults,
                filters: {
                    insight: InsightType.FUNNELS,
                },
            },
        })
        builtDataNodeLogic.mount()

        logic = funnelCorrelationDetailsLogic(defaultProps)
        logic.mount()
    })

    describe('correlationMatrixAndScore', () => {
        it('returns calculated values based on selected details', async () => {
            await expectLogic(logic, () =>
                logic.actions.openCorrelationDetailsModal({
                    event: { event: 'some event', elements: [], properties: {} },
                    success_people_url: '',
                    failure_people_url: '',
                    success_count: 2,
                    failure_count: 4,
                    odds_ratio: 3,
                    correlation_type: FunnelCorrelationType.Success,
                    result_type: FunnelCorrelationResultsType.Events,
                })
            ).toMatchValues({
                correlationMatrixAndScore: {
                    correlationScore: expect.anything(),
                    correlationScoreStrength: 'weak',
                    truePositive: 2,
                    falsePositive: 2,
                    trueNegative: 11,
                    falseNegative: 4,
                },
            })

            expect(logic.values.correlationMatrixAndScore.correlationScore).toBeCloseTo(0.204)
        })
    })
})

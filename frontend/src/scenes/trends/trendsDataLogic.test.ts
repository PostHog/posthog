import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { trendsDataLogic } from './trendsDataLogic'

import { InsightLogicProps, InsightModel } from '~/types'
import { DataNode } from '~/queries/schema'
import { trendResult } from './__mocks__/trendsDataLogicMocks'

let logic: ReturnType<typeof trendsDataLogic.build>
let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

async function initTrendsDataLogic(): Promise<void> {
    builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
    builtDataNodeLogic.mount()
    await expectLogic(dataNodeLogic).toFinishAllListeners()

    logic = trendsDataLogic(insightProps)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
}

describe('trendsDataLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        await initTrendsDataLogic()
    })

    describe('based on insightDataLogic', () => {
        describe('results', () => {
            it.skip('with non-trends insight', async () => {
                await expectLogic(logic).toMatchValues({
                    insight: expect.objectContaining({ filters: {} }),
                    results: [],
                })
            })

            it('for standard trend', async () => {
                const insight: Partial<InsightModel> = {
                    result: trendResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    results: trendResult.result,
                })
            })
        })

        //     describe('steps', () => {
        //         it('with time-to-convert funnel', async () => {
        //             const query: FunnelsQuery = {
        //                 kind: NodeKind.FunnelsQuery,
        //                 series: [],
        //                 funnelsFilter: {
        //                     funnel_viz_type: FunnelVizType.TimeToConvert,
        //                 },
        //             }
        //             const insight: Partial<InsightModel> = {
        //                 filters: {
        //                     insight: InsightType.FUNNELS,
        //                 },
        //                 result: funnelResultTimeToConvert.result,
        //             }

        //             await expectLogic(logic, () => {
        //                 logic.actions.updateQuerySource(query)
        //                 builtDataNodeLogic.actions.loadDataSuccess(insight)
        //             }).toMatchValues({
        //                 steps: [],
        //             })
        //         })

        //         it('for standard funnel', async () => {
        //             const insight: Partial<InsightModel> = {
        //                 filters: {
        //                     insight: InsightType.FUNNELS,
        //                 },
        //                 result: funnelResult.result,
        //             }

        //             await expectLogic(logic, () => {
        //                 builtDataNodeLogic.actions.loadDataSuccess(insight)
        //             }).toMatchValues({
        //                 steps: funnelResult.result,
        //             })
        //         })

        //         it('with breakdown', async () => {
        //             const insight: Partial<InsightModel> = {
        //                 filters: {
        //                     insight: InsightType.FUNNELS,
        //                 },
        //                 result: funnelResultWithBreakdown.result,
        //             }

        //             await expectLogic(logic, () => {
        //                 builtDataNodeLogic.actions.loadDataSuccess(insight)
        //             }).toMatchValues({
        //                 steps: expect.arrayContaining([
        //                     expect.objectContaining({
        //                         count: 201,
        //                         nested_breakdown: expect.arrayContaining([
        //                             expect.objectContaining({ breakdown: ['Chrome'], count: 136 }),
        //                             expect.objectContaining({ breakdown: ['Firefox'], count: 53 }),
        //                             expect.objectContaining({ breakdown: ['Safari'], count: 12 }),
        //                         ]),
        //                     }),
        //                     expect.objectContaining({
        //                         count: 99,
        //                         nested_breakdown: expect.arrayContaining([
        //                             expect.objectContaining({ breakdown: ['Chrome'], count: 66 }),
        //                             expect.objectContaining({ breakdown: ['Firefox'], count: 27 }),
        //                             expect.objectContaining({ breakdown: ['Safari'], count: 6 }),
        //                         ]),
        //                     }),
        //                 ]),
        //             })
        //         })

        //         it('with multi breakdown', async () => {
        //             const insight: Partial<InsightModel> = {
        //                 filters: {
        //                     insight: InsightType.FUNNELS,
        //                 },
        //                 result: funnelResultWithMultiBreakdown.result,
        //             }

        //             await expectLogic(logic, () => {
        //                 builtDataNodeLogic.actions.loadDataSuccess(insight)
        //             }).toMatchValues({
        //                 steps: expect.arrayContaining([
        //                     expect.objectContaining({
        //                         count: 69,
        //                         nested_breakdown: expect.arrayContaining([
        //                             expect.objectContaining({ breakdown: ['Chrome', 'Mac OS X'], count: 49 }),
        //                             expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 15 }),
        //                             expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 5 }),
        //                         ]),
        //                     }),
        //                     expect.objectContaining({
        //                         count: 37,
        //                         nested_breakdown: expect.arrayContaining([
        //                             expect.objectContaining({ breakdown: ['Chrome', 'Mac OS X'], count: 26 }),
        //                             expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 8 }),
        //                             expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 3 }),
        //                         ]),
        //                     }),
        //                 ]),
        //             })
        //         })
        //     })
    })
})

import { expectLogic } from 'kea-test-utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, LifecycleQuery, NodeKind, TrendsQuery } from '~/queries/schema'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, InsightLogicProps, InsightModel } from '~/types'

import { lifecycleResult, trendPieResult, trendResult } from './__mocks__/trendsDataLogicMocks'
import { trendsDataLogic } from './trendsDataLogic'

let logic: ReturnType<typeof trendsDataLogic.build>
let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

async function initTrendsDataLogic(): Promise<void> {
    builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
    builtDataNodeLogic.mount()
    await expectLogic(dataNodeLogic).toFinishAllListeners()

    insightDataLogic(insightProps).mount()
    insightVizDataLogic(insightProps).mount()

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

        describe('indexedResults', () => {
            it('for standard trend', async () => {
                const insight: Partial<InsightModel> = {
                    result: trendResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    indexedResults: [{ ...trendResult.result[0], id: 0, seriesIndex: 0 }],
                })
            })

            it('for pie visualization', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsPie,
                    },
                }
                const insight: Partial<InsightModel> = {
                    result: trendPieResult.result,
                }

                await expectLogic(logic, () => {
                    insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    indexedResults: [
                        expect.objectContaining({
                            aggregated_value: 3377681,
                            id: 0,
                            seriesIndex: 2,
                        }),
                        expect.objectContaining({
                            aggregated_value: 874570,
                            id: 1,
                            seriesIndex: 1,
                        }),
                        expect.objectContaining({
                            aggregated_value: 553348,
                            id: 2,
                            seriesIndex: 0,
                        }),
                    ],
                })
            })

            it('for lifecycle insight', async () => {
                const query: LifecycleQuery = {
                    kind: NodeKind.LifecycleQuery,
                    series: [],
                    lifecycleFilter: {
                        toggledLifecycles: ['new', 'dormant', 'resurrecting'],
                    },
                }
                const insight: Partial<InsightModel> = {
                    result: lifecycleResult.result,
                }

                await expectLogic(logic, () => {
                    insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    indexedResults: [
                        expect.objectContaining({
                            count: -50255.0,
                            status: 'dormant',
                            id: 0,
                            seriesIndex: 1,
                        }),
                        expect.objectContaining({
                            count: 11612.0,
                            status: 'resurrecting',
                            id: 1,
                            seriesIndex: 3,
                        }),
                        expect.objectContaining({
                            count: 35346.0,
                            status: 'new',
                            id: 2,
                            seriesIndex: 0,
                        }),
                    ],
                })
            })
        })
    })
})

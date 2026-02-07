import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, LifecycleQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, InsightLogicProps, InsightModel } from '~/types'

import { breakdownPieResult, lifecycleResult, trendPieResult, trendResult } from './__mocks__/trendsDataLogicMocks'
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
                    indexedResults: [{ ...trendResult.result[0], id: 0, seriesIndex: 0, colorIndex: 0 }],
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

            it('sorts correctly for pie visualization with null and other labels', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsPie,
                    },
                }
                const insight: Partial<InsightModel> = {
                    result: breakdownPieResult.result,
                }

                await expectLogic(logic, () => {
                    insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    indexedResults: [
                        expect.objectContaining({
                            aggregated_value: 801,
                            id: 0,
                            seriesIndex: 2,
                        }),
                        expect.objectContaining({
                            aggregated_value: 27,
                            id: 1,
                            seriesIndex: 0,
                        }),
                        expect.objectContaining({
                            aggregated_value: 9,
                            id: 2,
                            seriesIndex: 5,
                        }),
                        expect.objectContaining({
                            aggregated_value: 2,
                            id: 3,
                            seriesIndex: 4,
                        }),
                        expect.objectContaining({
                            aggregated_value: 25_567,
                            id: 4,
                            seriesIndex: 3,
                        }),
                        expect.objectContaining({
                            aggregated_value: 322,
                            id: 5,
                            seriesIndex: 1,
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
                    labelGroupType: 'people',
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

                query.aggregation_group_type_index = 1
                await expectLogic(logic, () => {
                    insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    labelGroupType: 1,
                })
            })
        })
    })

    describe('incomplete period display', () => {
        function makeTrendResultWithDays(days: string[]): Partial<InsightModel> {
            return {
                result: [
                    {
                        ...trendResult.result[0],
                        data: days.map((_, i) => (i + 1) * 100),
                        labels: days.map((d) => dayjs(d).format('D-MMM-YYYY')),
                        days,
                    },
                ],
            }
        }

        function todayAndPreviousDays(count: number): string[] {
            const days: string[] = []
            for (let i = count - 1; i >= 0; i--) {
                days.push(dayjs().subtract(i, 'day').format('YYYY-MM-DD'))
            }
            return days
        }

        it('defaults incompletePeriodDisplay to dashed', async () => {
            await expectLogic(logic).toMatchValues({
                incompletePeriodDisplay: 'dashed',
            })
        })

        it.each([
            ['dashed' as const, 'dashed'],
            ['solid' as const, 'solid'],
            ['hidden' as const, 'hidden'],
        ])('reads incompletePeriodDisplay=%s from trendsFilter', async (setting, expected) => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: { incompletePeriodDisplay: setting },
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
            }).toMatchValues({
                incompletePeriodDisplay: expected,
            })
        })

        it('visibleIndexedResults truncates data when hidden and has incomplete period', async () => {
            const days = todayAndPreviousDays(7)
            const insight = makeTrendResultWithDays(days)

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: { incompletePeriodDisplay: 'hidden' },
                interval: 'day',
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            })

            const { visibleIndexedResults, indexedResults, incompletenessOffsetFromEnd } = logic.values
            expect(incompletenessOffsetFromEnd).toBeLessThan(0)
            const expectedLength = indexedResults[0].data.length + incompletenessOffsetFromEnd
            expect(visibleIndexedResults[0].data).toHaveLength(expectedLength)
            expect(visibleIndexedResults[0].days).toHaveLength(expectedLength)
            expect(visibleIndexedResults[0].labels).toHaveLength(expectedLength)
        })

        it.each(['dashed' as const, 'solid' as const])(
            'visibleIndexedResults returns full data for %s mode',
            async (mode) => {
                const days = todayAndPreviousDays(7)
                const insight = makeTrendResultWithDays(days)

                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                    trendsFilter: { incompletePeriodDisplay: mode },
                    interval: 'day',
                }

                await expectLogic(logic, () => {
                    insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                })

                const { visibleIndexedResults, indexedResults } = logic.values
                expect(visibleIndexedResults[0].data).toHaveLength(indexedResults[0].data.length)
            }
        )

        it('visibleIndexedResults returns full data when no incomplete period exists', async () => {
            const insight: Partial<InsightModel> = {
                result: trendResult.result,
            }

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: { incompletePeriodDisplay: 'hidden' },
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            })

            const { visibleIndexedResults, indexedResults, incompletenessOffsetFromEnd } = logic.values
            expect(incompletenessOffsetFromEnd).toBe(0)
            expect(visibleIndexedResults[0].data).toHaveLength(indexedResults[0].data.length)
        })
    })
})

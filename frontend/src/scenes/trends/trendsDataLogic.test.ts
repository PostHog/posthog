import { expectLogic } from 'kea-test-utils'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getTrendResultCustomizationKey } from 'scenes/insights/utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, LifecycleQuery, NodeKind, ResultCustomizationBy, TrendsQuery } from '~/queries/schema/schema-general'
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
    insightLogic(insightProps).mount()
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

    describe('showMovingAverage', () => {
        it('is true for area graph with toggle enabled', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: {
                    display: ChartDisplayType.ActionsAreaGraph,
                    showMovingAverage: true,
                },
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
            }).toMatchValues({
                showMovingAverage: true,
            })
        })

        it('is false for area graph on non-linear scale', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: {
                    display: ChartDisplayType.ActionsAreaGraph,
                    showMovingAverage: true,
                    yAxisScaleType: 'log10',
                },
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
            }).toMatchValues({
                showMovingAverage: false,
            })
        })
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

    describe('legend series isolation selectors', () => {
        it.each([
            [
                'single series',
                [trendPieResult.result[0]],
                {
                    indexedResults: expect.arrayContaining([expect.any(Object)]),
                    legendSeriesIsolationMenuEligible: false,
                },
            ],
            [
                'multiple series (default state)',
                trendPieResult.result,
                {
                    areAllSeriesVisible: true,
                    showLegendIsolateSeriesItem: true,
                    legendSeriesIsolationMenuEligible: true,
                },
            ],
        ] as const)('%s', async (_label, result, expectedValues) => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
                trendsFilter: {
                    display: ChartDisplayType.ActionsPie,
                },
            }
            const insight: Partial<InsightModel> = { result }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues(expectedValues)

            if (result.length === 1) {
                expect(logic.values.indexedResults).toHaveLength(1)
            }
        })

        it('hides isolate menu item when every series is hidden', async () => {
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
                indexedResults: expect.any(Array),
            })

            const indexedResults = logic.values.indexedResults

            await expectLogic(logic, () => {
                logic.actions.toggleAllResultsHidden(indexedResults, true)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                areAllSeriesVisible: false,
                showLegendIsolateSeriesItem: false,
            })
        })

        it('getIsOnlyVisibleSeriesInLegend is true only for the sole visible series', async () => {
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
            }).toFinishAllListeners()

            const indexedResults = logic.values.indexedResults
            const solo = indexedResults[0]

            await expectLogic(logic, () => {
                logic.actions.toggleOtherSeriesHidden(solo)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                areAllSeriesVisible: false,
                showLegendIsolateSeriesItem: true,
            })

            const { getIsOnlyVisibleSeriesInLegend } = logic.values
            expect(indexedResults.map((r) => getIsOnlyVisibleSeriesInLegend(r))).toEqual([
                true,
                ...indexedResults.slice(1).map(() => false),
            ])
        })

        it('toggleAllResultsHidden preserves per-series color when bulk hiding', async () => {
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
            }).toFinishAllListeners()

            const indexedResults = logic.values.indexedResults
            const { resultCustomizationBy } = logic.values
            const key0 = getTrendResultCustomizationKey(resultCustomizationBy, indexedResults[0])

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(insightProps)?.actions.updateInsightFilter({
                    resultCustomizations: {
                        [key0]: {
                            assignmentBy: ResultCustomizationBy.Value,
                            color: 'preset-5',
                        },
                    },
                })
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.toggleAllResultsHidden(indexedResults, true)
            }).toFinishAllListeners()

            const resultCustomizations = logic.values.resultCustomizations as
                | Record<string, { color?: string; hidden?: boolean }>
                | undefined
            expect(resultCustomizations?.[key0]?.color).toBe('preset-5')
            expect(resultCustomizations?.[key0]?.hidden).toBe(true)
        })

        it('legendSeriesIsolationMenuEligible stays true when dashboard filters override is active', async () => {
            const propsWithOverrides: InsightLogicProps = {
                dashboardItemId: undefined,
                filtersOverride: { date_from: '-7d' } as InsightLogicProps['filtersOverride'],
            }

            builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
            builtDataNodeLogic.mount()
            await expectLogic(dataNodeLogic).toFinishAllListeners()

            insightDataLogic(propsWithOverrides).mount()
            insightLogic(propsWithOverrides).mount()
            insightVizDataLogic(propsWithOverrides).mount()

            const logicWithOverrides = trendsDataLogic(propsWithOverrides)
            logicWithOverrides.mount()
            await expectLogic(logicWithOverrides).toFinishAllListeners()

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

            await expectLogic(logicWithOverrides, () => {
                insightVizDataLogic.findMounted(propsWithOverrides)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                legendSeriesIsolationMenuEligible: true,
            })
        })
    })
})

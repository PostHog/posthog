import { expectLogic } from 'kea-test-utils'
import timekeeper from 'timekeeper'

import { AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE } from 'scenes/insights/filters/aggregationTargetUtils'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelConversionWindowTimeUnit, FunnelVizType, InsightLogicProps, InsightModel, InsightType } from '~/types'

import {
    funnelResult,
    funnelResultStepsBreakdownCompare,
    funnelResultStepsCompare,
    funnelResultTimeToConvert,
    funnelResultTimeToConvertCompare,
    funnelResultTimeToConvertWithoutConversions,
    funnelResultTrends,
    funnelResultTrendsCompare,
    funnelResultTrendsCompareWithBreakdown,
    funnelResultWithBreakdown,
    funnelResultWithMultiBreakdown,
} from './__mocks__/funnelDataLogicMocks'
import { funnelDataLogic } from './funnelDataLogic'
import { dimPreviousPeriodColor, getVisibilityKey } from './funnelUtils'

let logic: ReturnType<typeof funnelDataLogic.build>
let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

async function initFunnelDataLogic(): Promise<void> {
    teamLogic.mount()
    await expectLogic(teamLogic).toFinishAllListeners()

    builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
    builtDataNodeLogic.mount()
    await expectLogic(dataNodeLogic).toFinishAllListeners()

    logic = funnelDataLogic(insightProps)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
}

describe('funnelDataLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        await initFunnelDataLogic()
    })

    describe('funnel viz types', () => {
        it('with non-funnel insight', async () => {
            await expectLogic(logic).toMatchValues({
                querySource: null,
                isStepsFunnel: null,
                isTimeToConvertFunnel: null,
                isTrendsFunnel: null,
            })
        })

        it('with missing funnelsFilter', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.FunnelsQuery }),
                isStepsFunnel: true,
                isTimeToConvertFunnel: false,
                isTrendsFunnel: false,
            })
        })

        it('for steps viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.FunnelsQuery }),
                isStepsFunnel: true,
                isTimeToConvertFunnel: false,
                isTrendsFunnel: false,
            })
        })

        it('for time to convert viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.TimeToConvert,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.FunnelsQuery }),
                isStepsFunnel: false,
                isTimeToConvertFunnel: true,
                isTrendsFunnel: false,
            })
        })

        it('for trends viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Trends,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.FunnelsQuery }),
                isStepsFunnel: false,
                isTimeToConvertFunnel: false,
                isTrendsFunnel: true,
            })
        })
    })

    describe('empty funnel', () => {
        it('with non-funnel insight', async () => {
            await expectLogic(logic).toMatchValues({
                querySource: null,
                isEmptyFunnel: null,
            })
        })

        it('for empty funnel', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.FunnelsQuery }),
                isEmptyFunnel: true,
            })
        })

        it('for non-empty funnel', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [{ kind: NodeKind.EventsNode }],
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.FunnelsQuery }),
                isEmptyFunnel: false,
            })
        })
    })

    describe('aggregationTargetLabel', () => {
        it('uses the custom data warehouse entity label for custom aggregation targets', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    customAggregationTarget: true,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                aggregationTargetLabel: AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE,
            })
        })
    })

    describe('based on insightDataLogic', () => {
        describe('results', () => {
            it('for standard funnel', async () => {
                const insight: Partial<InsightModel> = {
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    results: funnelResult.result,
                })
            })

            it('with breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    result: funnelResultWithBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    results: expect.arrayContaining([
                        expect.arrayContaining([
                            expect.objectContaining({
                                breakdown_value: ['Chrome'],
                                breakdown: ['Chrome'],
                            }),
                        ]),
                    ]),
                })
            })

            it('with breakdown and no results', async () => {
                const insight: Partial<InsightModel> = {
                    result: [],
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    results: expect.arrayContaining([]),
                })
            })

            it('with multi breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    result: funnelResultWithMultiBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    results: expect.arrayContaining([
                        expect.arrayContaining([
                            expect.objectContaining({
                                breakdown_value: ['Chrome', 'Mac OS X'],
                                breakdown: ['Chrome', 'Mac OS X'],
                            }),
                        ]),
                    ]),
                })
            })
        })

        describe('steps', () => {
            it('with time-to-convert funnel', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultTimeToConvert.result,
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    steps: [],
                })
            })

            it('for standard funnel', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    steps: funnelResult.result,
                })
            })

            it('with breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    steps: expect.arrayContaining([
                        expect.objectContaining({
                            count: 201,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome'], count: 136 }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 53 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 12 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 99,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome'], count: 66 }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 27 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 6 }),
                            ]),
                        }),
                    ]),
                })
            })

            it('with multi breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithMultiBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    steps: expect.arrayContaining([
                        expect.objectContaining({
                            count: 69,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome', 'Mac OS X'], count: 49 }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 15 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 5 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 37,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome', 'Mac OS X'], count: 26 }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 8 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 3 }),
                            ]),
                        }),
                    ]),
                })
            })
        })

        describe('stepsWithConversionMetrics', () => {
            it('for standard funnel', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    stepsWithConversionMetrics: expect.arrayContaining([
                        expect.objectContaining({
                            droppedOffFromPrevious: 0,
                            conversionRates: {
                                fromBasisStep: 1,
                                fromPrevious: 1,
                                total: 1,
                            },
                        }),
                        expect.objectContaining({
                            droppedOffFromPrevious: 157,
                            conversionRates: {
                                fromBasisStep: 0.46048109965635736,
                                fromPrevious: 0.46048109965635736,
                                total: 0.46048109965635736,
                            },
                        }),
                    ]),
                })
            })

            it('with breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    stepsWithConversionMetrics: expect.arrayContaining([
                        expect.objectContaining({
                            count: 201,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome'],
                                    count: 136,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 53 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 12 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 99,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome'],
                                    count: 66,
                                    droppedOffFromPrevious: 70,
                                    conversionRates: {
                                        fromPrevious: 0.4852941176470588,
                                        total: 0.4852941176470588,
                                        fromBasisStep: 0.4852941176470588,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 27 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 6 }),
                            ]),
                        }),
                    ]),
                })
            })

            it('with multi breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithMultiBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    stepsWithConversionMetrics: expect.arrayContaining([
                        expect.objectContaining({
                            count: 69,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome', 'Mac OS X'],
                                    count: 49,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 15 }),
                                expect.objectContaining({
                                    breakdown: ['Internet Explorer', 'Windows'],
                                    count: 5,
                                }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 37,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome', 'Mac OS X'],
                                    count: 26,
                                    droppedOffFromPrevious: 23,
                                    conversionRates: {
                                        fromPrevious: 0.5306122448979592,
                                        total: 0.5306122448979592,
                                        fromBasisStep: 0.5306122448979592,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 8 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 3 }),
                            ]),
                        }),
                    ]),
                })
            })
        })

        describe('flattenedBreakdowns', () => {
            it('for standard funnel', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    flattenedBreakdowns: [
                        {
                            rowKey: 'baseline_0',
                            breakdown: ['baseline'],
                            breakdown_value: ['Baseline'],
                            isBaseline: true,
                            breakdownIndex: 0,
                            steps: [
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                    count: 291,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                }),
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                    count: 134,
                                    droppedOffFromPrevious: 157,
                                    conversionRates: {
                                        fromPrevious: 0.46048109965635736,
                                        total: 0.46048109965635736,
                                        fromBasisStep: 0.46048109965635736,
                                    },
                                }),
                            ],
                            conversionRates: { total: 0.46048109965635736 },
                        },
                    ],
                })
            })

            it('with breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    flattenedBreakdowns: [
                        expect.objectContaining({ breakdown: ['baseline'] }),
                        expect.objectContaining({
                            rowKey: 'Chrome_1',
                            breakdown: ['Chrome'],
                            breakdown_value: ['Chrome'],
                            isBaseline: false,
                            breakdownIndex: 1,
                            steps: [
                                expect.objectContaining({
                                    count: 136,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({
                                    count: 66,
                                    droppedOffFromPrevious: 70,
                                    conversionRates: {
                                        fromPrevious: 0.4852941176470588,
                                        total: 0.4852941176470588,
                                        fromBasisStep: 0.4852941176470588,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                            ],
                            conversionRates: { total: 0.4852941176470588 },
                            significant: false,
                        }),
                        expect.objectContaining({ breakdown: ['Firefox'] }),
                        expect.objectContaining({ breakdown: ['Safari'] }),
                    ],
                })
            })

            it('with multi breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithMultiBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    flattenedBreakdowns: [
                        expect.objectContaining({ breakdown: ['baseline'] }),
                        expect.objectContaining({
                            rowKey: 'Chrome_Mac OS X_1',
                            breakdown: ['Chrome', 'Mac OS X'],
                            breakdown_value: ['Chrome', 'Mac OS X'],
                            isBaseline: false,
                            breakdownIndex: 1,
                            steps: [
                                expect.objectContaining({
                                    count: 49,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({
                                    count: 26,
                                    droppedOffFromPrevious: 23,
                                    conversionRates: {
                                        fromBasisStep: 0.5306122448979592,
                                        fromPrevious: 0.5306122448979592,
                                        total: 0.5306122448979592,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                            ],
                            conversionRates: { total: 0.5306122448979592 },
                            significant: false,
                        }),
                        expect.objectContaining({ breakdown: ['Chrome', 'Linux'] }),
                        expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'] }),
                    ],
                })
            })
        })

        describe('visibleStepsWithConversionMetrics', () => {
            it('for standard funnel', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    visibleStepsWithConversionMetrics: [
                        expect.objectContaining({
                            name: '$pageview',
                            count: 291,
                            conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                        }),
                        expect.objectContaining({
                            name: '$pageview',
                            count: 134,
                            conversionRates: {
                                fromPrevious: 0.46048109965635736,
                                total: 0.46048109965635736,
                                fromBasisStep: 0.46048109965635736,
                            },
                            nested_breakdown: [
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                }),
                            ],
                        }),
                    ],
                })
            })

            it('with breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithBreakdown.result,
                }
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        hiddenLegendBreakdowns: ['Firefox'],
                    },
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    visibleStepsWithConversionMetrics: [
                        expect.objectContaining({
                            name: '$pageview',
                            count: 201,
                            conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                        }),
                        expect.objectContaining({
                            name: '$pageview',
                            count: 99,
                            conversionRates: {
                                fromPrevious: 0.4925373134328358,
                                total: 0.4925373134328358,
                                fromBasisStep: 0.4925373134328358,
                            },
                            nested_breakdown: [
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                    count: 99,
                                }),
                                expect.objectContaining({
                                    breakdown_value: ['Chrome'],
                                    count: 66,
                                }),
                                expect.objectContaining({
                                    breakdown_value: ['Safari'],
                                    count: 6,
                                }),
                            ],
                        }),
                    ],
                })
            })

            it('with multi breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithMultiBreakdown.result,
                }
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        hiddenLegendBreakdowns: ['Chrome::Mac OS X'],
                    },
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)

                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    visibleStepsWithConversionMetrics: [
                        expect.objectContaining({
                            name: '$pageview',
                            count: 69,
                            conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                        }),
                        expect.objectContaining({
                            name: '$pageview',
                            count: 37,
                            conversionRates: {
                                fromPrevious: 0.5362318840579711,
                                total: 0.5362318840579711,
                                fromBasisStep: 0.5362318840579711,
                            },
                            nested_breakdown: [
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                    count: 37,
                                }),
                                expect.objectContaining({
                                    breakdown_value: ['Chrome', 'Linux'],
                                    count: 8,
                                }),
                                expect.objectContaining({
                                    breakdown_value: ['Internet Explorer', 'Windows'],
                                    count: 3,
                                }),
                            ],
                        }),
                    ],
                })
            })
        })
    })

    describe('breakdownSorting', () => {
        const insight: Partial<InsightModel> = {
            filters: { insight: InsightType.FUNNELS },
            result: funnelResultWithBreakdown.result,
        }

        const getBreakdownOrder = (items: unknown[]): unknown[] =>
            items.map((b: any) => {
                const v = b.breakdown_value
                return Array.isArray(v) ? v[0] : v
            })

        it.each([
            ['breakdown_value', ['Baseline', 'Chrome', 'Firefox', 'Safari']],
            ['-breakdown_value', ['Safari', 'Firefox', 'Chrome', 'Baseline']],
            ['step_0_conversion', ['Safari', 'Firefox', 'Chrome', 'Baseline']],
            ['-step_0_conversion', ['Baseline', 'Chrome', 'Firefox', 'Safari']],
            ['step_1_conversion', ['Safari', 'Firefox', 'Chrome', 'Baseline']],
            ['-step_1_conversion', ['Baseline', 'Chrome', 'Firefox', 'Safari']],
        ])('flattenedBreakdowns sorts by %s', async (breakdownSorting: string, expectedOrder: string[]) => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { breakdownSorting },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            const order = getBreakdownOrder(logic.values.flattenedBreakdowns)
            expect(order).toEqual(expectedOrder)
        })

        it('visibleStepsWithConversionMetrics matches flattenedBreakdowns order', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { breakdownSorting: '-step_1_conversion' },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            const { flattenedBreakdowns, visibleStepsWithConversionMetrics } = logic.values
            const graphOrder = getBreakdownOrder(visibleStepsWithConversionMetrics[1].nested_breakdown ?? [])
            expect(graphOrder).toEqual(getBreakdownOrder(flattenedBreakdowns))
        })
    })

    describe('time to convert funnel', () => {
        describe('timeConversionResults', () => {
            it('with time-to-convert funnel', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultTimeToConvert.result,
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    timeConversionResults: funnelResultTimeToConvert.result,
                })
            })

            it('with other funnel', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    timeConversionResults: null,
                })
            })
        })

        describe('histogramGraphData', () => {
            it('without results', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: {
                        ...funnelResultTimeToConvert.result,
                        bins: [],
                    },
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    histogramGraphData: null,
                })
            })

            it('without conversions', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultTimeToConvertWithoutConversions.result,
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    histogramGraphData: [],
                })
            })

            it('with time-to-convert funnel', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultTimeToConvert.result,
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    histogramGraphData: [
                        { bin0: 4, bin1: 73591, count: 74, id: 4, label: '54.8%' },
                        { bin0: 73591, bin1: 147178, count: 24, id: 73591, label: '17.8%' },
                        { bin0: 147178, bin1: 220765, count: 24, id: 147178, label: '17.8%' },
                        { bin0: 220765, bin1: 294352, count: 10, id: 220765, label: '7.4%' },
                        { bin0: 294352, bin1: 367939, count: 2, id: 294352, label: '1.5%' },
                        { bin0: 367939, bin1: 441526, count: 1, id: 367939, label: '0.7%' },
                        { bin0: 441526, bin1: 515113, count: 0, id: 441526, label: '' },
                    ],
                })
            })

            it('splits the current and previous periods when comparing', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                    compareFilter: { compare: true },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultTimeToConvertCompare.result,
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    // Current period: the 'current'-tagged bins, on the shared boundaries.
                    histogramGraphData: [
                        expect.objectContaining({ bin0: 4, count: 74 }),
                        expect.objectContaining({ bin0: 73591, count: 24 }),
                        expect.objectContaining({ bin0: 147178, count: 10 }),
                    ],
                    // Previous period: the 'previous'-tagged bins, on the same boundaries.
                    histogramGraphDataPrevious: [
                        expect.objectContaining({ bin0: 4, count: 52 }),
                        expect.objectContaining({ bin0: 73591, count: 31 }),
                        expect.objectContaining({ bin0: 147178, count: 17 }),
                    ],
                })
            })

            it('has no previous-period data when not comparing', async () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {
                        funnelVizType: FunnelVizType.TimeToConvert,
                    },
                }
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultTimeToConvert.result,
                }

                await expectLogic(logic, () => {
                    logic.actions.updateQuerySource(query)
                    builtDataNodeLogic.actions.loadDataSuccess(insight)
                }).toMatchValues({
                    histogramGraphDataPrevious: null,
                })
            })
        })
    })

    describe('hasFunnelResults', () => {
        it('for steps viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
                },
            }

            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResult.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                hasFunnelResults: true,
            })
        })

        it('for time to convert viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.TimeToConvert,
                },
            }

            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResultTimeToConvert.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                hasFunnelResults: true,
            })
        })

        it('for trends viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Trends,
                },
            }

            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResultTrends.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                hasFunnelResults: true,
            })
        })
    })

    describe('conversionMetrics', () => {
        it('for steps viz with multiple steps', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
                },
            }

            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResult.result,
                // Funnel-level median is carried as a top-level field on the response, not summed from steps.
                total_median_conversion_time: 208.75,
            } as any

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                conversionMetrics: {
                    medianTime: 208.75,
                    stepRate: 0.46048109965635736,
                    totalRate: 0.46048109965635736,
                },
            })
        })

        it('for time to convert viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.TimeToConvert,
                },
            }
            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResultTimeToConvert.result,
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                conversionMetrics: {
                    medianTime: 60492.5, // from backend
                    stepRate: 0,
                    totalRate: 0,
                },
            })
        })

        it('for trends viz', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Trends,
                },
            }

            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResultTrends.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                conversionMetrics: {
                    medianTime: null,
                    stepRate: 0,
                    totalRate: 0.7120000000000001, // avg(steps[0] / 100)
                },
            })
        })

        it('for steps viz when median is missing (old cache)', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.Steps,
                },
            }

            // No total_median_conversion_time — mirrors a result cached before the field existed.
            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResult.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                conversionMetrics: {
                    medianTime: null,
                    stepRate: 0.46048109965635736,
                    totalRate: 0.46048109965635736,
                },
            })
        })

        it('for time to convert viz when median is missing (old cache)', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelVizType: FunnelVizType.TimeToConvert,
                },
            }
            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: {
                    bins: (funnelResultTimeToConvert.result as any).bins,
                    average_conversion_time: (funnelResultTimeToConvert.result as any).average_conversion_time,
                },
            } as any

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                conversionMetrics: {
                    medianTime: null,
                    stepRate: 0,
                    totalRate: 0,
                },
            })
        })
    })

    describe('conversionWindow', () => {
        it('with defaults', async () => {
            await expectLogic(logic).toMatchValues({
                conversionWindow: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: 'day',
                },
            })
        })

        it('with conversion window', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 3,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Week,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                conversionWindow: {
                    funnelWindowInterval: 3,
                    funnelWindowIntervalUnit: 'week',
                },
            })
        })

        it('draft interval defaults to null before any edits', async () => {
            await expectLogic(logic).toMatchValues({
                conversionWindowInterval: null,
                conversionWindowUnit: null,
            })
        })

        it('setConversionWindowInterval updates the draft value', async () => {
            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(21)
            }).toMatchValues({
                conversionWindowInterval: 21,
            })
        })

        it('setConversionWindowUnit updates the draft unit', async () => {
            await expectLogic(logic, () => {
                logic.actions.setConversionWindowUnit(FunnelConversionWindowTimeUnit.Hour)
            }).toMatchValues({
                conversionWindowUnit: FunnelConversionWindowTimeUnit.Hour,
            })
        })

        it('commitConversionWindow resets to saved value when interval is empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(0)
                logic.actions.commitConversionWindow()
            })
                .toDispatchActions(['commitConversionWindow', 'setConversionWindowInterval'])
                .toMatchValues({
                    conversionWindowInterval: 14,
                })
        })

        it('commitConversionWindow clamps values to bounds', async () => {
            const funnelQuery: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(funnelQuery)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(9999)
                logic.actions.commitConversionWindow()
            }).toMatchValues({
                conversionWindowInterval: 365,
            })

            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(-5)
                logic.actions.commitConversionWindow()
            }).toMatchValues({
                conversionWindowInterval: 1,
            })
        })

        it('commitConversionWindow calls updateInsightFilter when interval changed', async () => {
            const funnelQuery: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(funnelQuery)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(21)
                logic.actions.commitConversionWindow()
            })
                .toDispatchActions(['commitConversionWindow', 'updateInsightFilter'])
                .toFinishAllListeners()
        })

        it('commitConversionWindow calls updateInsightFilter when only unit changed', async () => {
            const funnelQuery: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(funnelQuery)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setConversionWindowUnit(FunnelConversionWindowTimeUnit.Hour)
                logic.actions.commitConversionWindow()
            })
                .toDispatchActions(['commitConversionWindow', 'updateInsightFilter'])
                .toFinishAllListeners()
        })

        it('commitConversionWindow does not call updateInsightFilter when value unchanged', async () => {
            const funnelQuery: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }

            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(funnelQuery)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(14)
                logic.actions.commitConversionWindow()
            })
                .toNotHaveDispatchedActions(['updateInsightFilter'])
                .toFinishAllListeners()
        })
    })

    describe('incompletenessOffsetFromEnd', () => {
        beforeAll(() => {
            const lastResponseDay = funnelResultTrends.result[0].days.slice(-1)[0]
            timekeeper.freeze(new Date(lastResponseDay))
        })

        afterAll(() => {
            timekeeper.reset()
        })

        it('with defaults', async () => {
            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResultTrends.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                incompletenessOffsetFromEnd: -7,
            })
        })

        it('with conversion window', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 2,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }

            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.FUNNELS,
                },
                result: funnelResultTrends.result,
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                incompletenessOffsetFromEnd: -3,
            })
        })
    })

    describe('indexedSteps colorIndex pairing', () => {
        const trendsQuery: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [],
            funnelsFilter: {
                funnelVizType: FunnelVizType.Trends,
            },
        }

        async function loadResult(result: unknown): Promise<void> {
            const insight: Partial<InsightModel> = {
                filters: { insight: InsightType.FUNNELS },
                result: result as InsightModel['result'],
            }
            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(trendsQuery)
            }).toFinishAllListeners()
        }

        it('assigns colorIndex 0 to a single-period trends result', async () => {
            await loadResult(funnelResultTrends.result)
            const steps = logic.values.indexedSteps as Array<Record<string, unknown>>
            expect(steps).toHaveLength(1)
            expect(steps[0].colorIndex).toBe(0)
            expect(steps[0].seriesIndex).toBe(0)
        })

        it('pairs current and previous on the same colorIndex without a breakdown', async () => {
            await loadResult(funnelResultTrendsCompare.result)
            const steps = logic.values.indexedSteps as Array<Record<string, unknown>>
            expect(steps).toHaveLength(2)
            expect(steps[0].colorIndex).toBe(0)
            expect(steps[1].colorIndex).toBe(0)
            expect(steps[0].seriesIndex).toBe(0)
            expect(steps[1].seriesIndex).toBe(1)
            expect(steps[0].compare_label).toBe('current')
            expect(steps[1].compare_label).toBe('previous')
            // The runner only sets `compare_label`; `indexedSteps` normalizes `compare: true`
            // so LineGraph.processDataset dims the previous-period series.
            expect(steps[0].compare).toBe(true)
            expect(steps[1].compare).toBe(true)
        })

        it('pairs current and previous per breakdown value', async () => {
            await loadResult(funnelResultTrendsCompareWithBreakdown.result)
            const steps = logic.values.indexedSteps as Array<Record<string, unknown>>
            expect(steps).toHaveLength(4)

            const byKey = (label: string, breakdownValue: string): Record<string, unknown> => {
                const found = steps.find((s) => s.compare_label === label && s.breakdown_value === breakdownValue)
                if (!found) {
                    throw new Error(`missing row ${label}/${breakdownValue}`)
                }
                return found
            }
            const currentUs = byKey('current', 'us')
            const previousUs = byKey('previous', 'us')
            const currentUk = byKey('current', 'uk')
            const previousUk = byKey('previous', 'uk')

            expect(currentUs.colorIndex).toBe(previousUs.colorIndex)
            expect(currentUk.colorIndex).toBe(previousUk.colorIndex)
            expect(currentUs.colorIndex).not.toBe(currentUk.colorIndex)
        })
    })

    describe('steps compare (grouped bars)', () => {
        const stepsQuery: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [],
            funnelsFilter: { funnelVizType: FunnelVizType.Steps },
            compareFilter: { compare: true },
        }

        async function loadStepsCompare(result: unknown): Promise<void> {
            const insight: Partial<InsightModel> = {
                filters: { insight: InsightType.FUNNELS },
                result: result as InsightModel['result'],
            }
            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(stepsQuery)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()
        }

        it('reshapes a compare-tagged flat result into one step per order with current+previous bars', async () => {
            await loadStepsCompare(funnelResultStepsCompare.result)

            const steps = logic.values.visibleStepsWithConversionMetrics
            // One column per funnel step (not one per period).
            expect(steps).toHaveLength(2)

            // Each step renders two bars: current then previous, tagged accordingly.
            steps.forEach((step) => {
                expect(step.nested_breakdown).toHaveLength(2)
                expect(step.nested_breakdown?.[0].compare_label).toBe('current')
                expect(step.nested_breakdown?.[1].compare_label).toBe('previous')
            })

            // Counts come from the respective period (current 200->100, previous 150->60).
            expect(steps[0].nested_breakdown?.[0].count).toBe(200)
            expect(steps[0].nested_breakdown?.[1].count).toBe(150)
            expect(steps[1].nested_breakdown?.[0].count).toBe(100)
            expect(steps[1].nested_breakdown?.[1].count).toBe(60)
        })

        it('scales both periods against a shared baseline so the previous bar reflects its volume', async () => {
            await loadStepsCompare(funnelResultStepsCompare.result)

            const steps = logic.values.visibleStepsWithConversionMetrics

            // Bar height (fromBasisStep) is relative to the larger period's first step (200).
            expect(steps[0].nested_breakdown?.[0].conversionRates.fromBasisStep).toBe(1) // 200/200
            expect(steps[0].nested_breakdown?.[1].conversionRates.fromBasisStep).toBe(150 / 200) // not full height
            expect(steps[1].nested_breakdown?.[0].conversionRates.fromBasisStep).toBe(100 / 200)
            expect(steps[1].nested_breakdown?.[1].conversionRates.fromBasisStep).toBe(60 / 200)

            // Tooltip conversion rates stay per-period: previous step 1 converts 60/150 of its own funnel.
            expect(steps[0].nested_breakdown?.[1].conversionRates.total).toBe(1)
            expect(steps[1].nested_breakdown?.[1].conversionRates.total).toBe(60 / 150)
        })

        it('renders the previous-period bar desaturated relative to the current bar', async () => {
            await loadStepsCompare(funnelResultStepsCompare.result)

            const step = logic.values.visibleStepsWithConversionMetrics[0]
            const currentSeries = step.nested_breakdown![0]
            const previousSeries = step.nested_breakdown![1]

            const currentColor = logic.values.getFunnelsColor(currentSeries)
            const previousColor = logic.values.getFunnelsColor(previousSeries)

            // Both bars share the base hue; the previous one is dimmed to 50% opacity.
            expect(previousColor).toBe(dimPreviousPeriodColor(currentColor))
            expect(previousColor).not.toBe(currentColor)
        })

        it('builds one baseline table row per period for a pure compare funnel', async () => {
            await loadStepsCompare(funnelResultStepsCompare.result)

            // Pure compare: current/previous bars are not real breakdown values, but each period
            // still gets a baseline row in the detailed results table.
            expect(logic.values.isComparedFunnel).toBe(true)
            expect(logic.values.isBreakdownCompareFunnel).toBe(false)

            const rows = logic.values.flattenedBreakdowns
            expect(rows.map((r) => [r.compare_label, r.breakdownIndex, r.colorIndex, r.isBaseline])).toEqual([
                ['current', 0, 0, true],
                ['previous', 1, 0, true],
            ])
            // Rows carry no breakdown value so their color/customization key matches the chart bars.
            expect(rows.map((r) => r.breakdown_value)).toEqual([undefined, undefined])
            // Each row aggregates its own period: current 200->100, previous 150->60.
            expect(rows[0].steps?.map((s) => s.count)).toEqual([200, 100])
            expect(rows[1].steps?.map((s) => s.count)).toEqual([150, 60])
            expect(rows[0].conversionRates?.total).toBe(0.5)
            expect(rows[1].conversionRates?.total).toBe(0.4)

            // The previous row's ribbon is the dimmed current color, matching the chart bars.
            expect(logic.values.getFunnelsColor(rows[1])).toBe(
                dimPreviousPeriodColor(logic.values.getFunnelsColor(rows[0]))
            )
        })

        it('leaves a non-compared steps funnel unchanged (single bar per step)', async () => {
            const stepsQueryNoCompare: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: FunnelVizType.Steps },
            }
            const insight: Partial<InsightModel> = {
                filters: { insight: InsightType.FUNNELS },
                result: funnelResult.result,
            }
            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(stepsQueryNoCompare)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            expect(logic.values.isComparedFunnel).toBe(false)
            const steps = logic.values.visibleStepsWithConversionMetrics
            expect(steps).toHaveLength(2)
            steps.forEach((step) => {
                expect(step.nested_breakdown).toHaveLength(1)
                expect(step.nested_breakdown?.[0].compare_label).toBeUndefined()
            })
        })
    })

    describe('steps breakdown compare (grouped bars)', () => {
        const stepsQuery: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [],
            funnelsFilter: { funnelVizType: FunnelVizType.Steps },
            breakdownFilter: { breakdown: '$browser' },
            compareFilter: { compare: true },
        }

        async function loadBreakdownCompare(result: unknown): Promise<void> {
            const insight: Partial<InsightModel> = {
                filters: { insight: InsightType.FUNNELS },
                result: result as InsightModel['result'],
            }
            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(stepsQuery)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()
        }

        it('pairs current+previous bars per breakdown value within each step', async () => {
            await loadBreakdownCompare(funnelResultStepsBreakdownCompare.result)

            expect(logic.values.isComparedFunnel).toBe(true)
            const steps = logic.values.visibleStepsWithConversionMetrics
            expect(steps).toHaveLength(2)

            // The baseline pair (both periods aggregated) leads, then Chrome (current 100) outranks
            // Safari (current 40): each value's pair grouped, current before previous.
            expect(
                steps[0].nested_breakdown?.map((b) => [getVisibilityKey(b.breakdown_value), b.compare_label])
            ).toEqual([
                ['Baseline', 'current'],
                ['Baseline', 'previous'],
                ['Chrome', 'current'],
                ['Chrome', 'previous'],
                ['Safari', 'current'],
                ['Safari', 'previous'],
            ])
            expect(steps[0].nested_breakdown?.map((b) => b.count)).toEqual([140, 105, 100, 80, 40, 25])

            // The step's aggregate (shown in the legend) is the current period's total only —
            // not current+previous summed together.
            expect(steps[0].count).toBe(140) // 100 Chrome + 40 Safari
            expect(steps[1].count).toBe(70) // 50 Chrome + 20 Safari
        })

        it('shares each period’s height across its breakdown values (larger period fills), keeping the first-step basis at later steps', async () => {
            await loadBreakdownCompare(funnelResultStepsBreakdownCompare.result)

            const [baselineCur, baselinePrev, chromeCur, chromePrev, safariCur, safariPrev] =
                logic.values.visibleStepsWithConversionMetrics[0].nested_breakdown!

            // At the first step every value converts 100% of its own entrants, so a period's values all
            // share one height — the period's share of the larger baseline: current (140) fills, previous
            // (105) → 105/140. Baseline, Chrome and Safari read identically within each period.
            expect(baselineCur.conversionRates.fromBasisStep).toBe(1)
            expect(baselinePrev.conversionRates.fromBasisStep).toBe(105 / 140)
            expect(chromeCur.conversionRates.fromBasisStep).toBe(1)
            expect(chromePrev.conversionRates.fromBasisStep).toBe(105 / 140)
            expect(safariCur.conversionRates.fromBasisStep).toBe(1)
            expect(safariPrev.conversionRates.fromBasisStep).toBe(105 / 140)

            // Later steps keep the first-step denominator (largest period's entrants, 140), so each
            // baseline bar reads as the share of that starting cohort still left: not a per-step
            // rescale, and not silently dropped past step 0.
            const [baselineCur1, baselinePrev1] = logic.values.visibleStepsWithConversionMetrics[1].nested_breakdown!
            expect(baselineCur1.count).toBe(70)
            expect(baselineCur1.conversionRates.fromBasisStep).toBe(70 / 140)
            expect(baselinePrev1.count).toBe(40)
            expect(baselinePrev1.conversionRates.fromBasisStep).toBe(40 / 140)
        })

        it('colors each breakdown value distinctly, desaturates its previous-period bar, and matches the table', async () => {
            await loadBreakdownCompare(funnelResultStepsBreakdownCompare.result)

            const [baselineCur, baselinePrev, chromeCur, chromePrev, safariCur, safariPrev] =
                logic.values.visibleStepsWithConversionMetrics[0].nested_breakdown!
            const color = logic.values.getFunnelsColor

            // Distinct hue per breakdown value, baseline included...
            expect(color(chromeCur)).not.toBe(color(safariCur))
            expect(color(baselineCur)).not.toBe(color(chromeCur))
            // ...with each value's previous-period bar the same hue, desaturated.
            expect(color(baselinePrev)).toBe(dimPreviousPeriodColor(color(baselineCur)))
            expect(color(chromePrev)).toBe(dimPreviousPeriodColor(color(chromeCur)))
            expect(color(safariPrev)).toBe(dimPreviousPeriodColor(color(safariCur)))

            // The chart bars now include the baseline the table always showed, in the same order, so
            // the two share colors bar-for-row instead of being shifted by one slot.
            const chartColors = logic.values.visibleStepsWithConversionMetrics[0].nested_breakdown!.map(color)
            expect(chartColors).toEqual(logic.values.flattenedBreakdowns.map(color))
        })

        it('doubles the breakdown table into one row per value and period', async () => {
            await loadBreakdownCompare(funnelResultStepsBreakdownCompare.result)

            // Breakdown + compare is distinguished from pure compare so breakdown behavior survives.
            expect(logic.values.isComparedFunnel).toBe(true)
            expect(logic.values.isBreakdownCompareFunnel).toBe(true)

            const rows = logic.values.flattenedBreakdowns
            expect(rows.map((r) => [getVisibilityKey(r.breakdown_value), r.compare_label])).toEqual([
                ['Baseline', 'current'],
                ['Baseline', 'previous'],
                ['Chrome', 'current'],
                ['Chrome', 'previous'],
                ['Safari', 'current'],
                ['Safari', 'previous'],
            ])
            // Unique row keys with pair-shared color positions.
            expect(rows.map((r) => r.breakdownIndex)).toEqual([0, 1, 2, 3, 4, 5])
            expect(rows.map((r) => r.colorIndex)).toEqual([0, 0, 1, 1, 2, 2])

            // The previous baseline has no upstream aggregate — it's synthesized from the previous
            // bars: 105 -> 40, with the period's weighted conversion time.
            expect(rows[1].steps?.map((s) => s.count)).toEqual([105, 40])
            expect(rows[1].conversionRates?.total).toBe(40 / 105)
            expect(rows[1].steps?.[1].average_conversion_time).toBe(4200)

            // Row ribbons pair up per value: previous is the dimmed current, distinct across values.
            const color = logic.values.getFunnelsColor
            expect(color(rows[3])).toBe(dimPreviousPeriodColor(color(rows[2])))
            expect(color(rows[2])).not.toBe(color(rows[4]))
        })

        it('hides both periods of a breakdown value when its legend entry is hidden', async () => {
            const insight: Partial<InsightModel> = {
                filters: { insight: InsightType.FUNNELS },
                result: funnelResultStepsBreakdownCompare.result as InsightModel['result'],
            }
            await expectLogic(logic, () => {
                const query: FunnelsQuery = {
                    ...stepsQuery,
                    funnelsFilter: { ...stepsQuery.funnelsFilter, hiddenLegendBreakdowns: ['Chrome'] },
                }
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            // Hiding Chrome drops its current AND previous bars; the baseline and Safari's pair remain.
            const visibleValues = logic.values.visibleStepsWithConversionMetrics[0].nested_breakdown?.map((b) => [
                getVisibilityKey(b.breakdown_value),
                b.compare_label,
            ])
            expect(visibleValues).toEqual([
                ['Baseline', 'current'],
                ['Baseline', 'previous'],
                ['Safari', 'current'],
                ['Safari', 'previous'],
            ])

            // The table still lists both of Chrome's period rows (just unchecked), so it can be
            // toggled back on.
            const breakdownValues = logic.values.flattenedBreakdowns
                .filter((b) => !b.isBaseline)
                .map((b) => getVisibilityKey(b.breakdown_value))
            expect(breakdownValues).toEqual(['Chrome', 'Chrome', 'Safari', 'Safari'])
        })

        it('hides both periods of the baseline when its legend entry is hidden', async () => {
            const insight: Partial<InsightModel> = {
                filters: { insight: InsightType.FUNNELS },
                result: funnelResultStepsBreakdownCompare.result as InsightModel['result'],
            }
            await expectLogic(logic, () => {
                const query: FunnelsQuery = {
                    ...stepsQuery,
                    funnelsFilter: { ...stepsQuery.funnelsFilter, hiddenLegendBreakdowns: ['Baseline'] },
                }
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            // The synthesized baseline pair takes a separate path than the value bars, so it must be
            // hidden too; the values keep their baseline-shifted orders (hence colors) while the
            // baseline is merely hidden.
            const visibleValues = logic.values.visibleStepsWithConversionMetrics[0].nested_breakdown?.map((b) => [
                getVisibilityKey(b.breakdown_value),
                b.compare_label,
                b.order,
            ])
            expect(visibleValues).toEqual([
                ['Chrome', 'current', 1],
                ['Chrome', 'previous', 1],
                ['Safari', 'current', 2],
                ['Safari', 'previous', 2],
            ])

            // The table still lists both baseline rows (just unchecked), so they can be toggled back on.
            expect(logic.values.flattenedBreakdowns.filter((b) => b.isBaseline)).toHaveLength(2)
        })
    })
})

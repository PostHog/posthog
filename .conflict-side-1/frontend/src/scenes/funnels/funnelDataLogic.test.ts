import { expectLogic } from 'kea-test-utils'
import timekeeper from 'timekeeper'

import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelConversionWindowTimeUnit, FunnelVizType, InsightLogicProps, InsightModel, InsightType } from '~/types'

import {
    funnelResult,
    funnelResultTimeToConvert,
    funnelResultTimeToConvertWithoutConversions,
    funnelResultTrends,
    funnelResultWithBreakdown,
    funnelResultWithMultiBreakdown,
} from './__mocks__/funnelDataLogicMocks'
import { funnelDataLogic } from './funnelDataLogic'

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
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
                logic.actions.updateQuerySource(query)
            }).toMatchValues({
                conversionMetrics: {
                    averageTime: 87098.67529697785,
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
                    averageTime: 86456.76, // from backend
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
                    averageTime: 0,
                    stepRate: 0,
                    totalRate: 0.7120000000000001, // avg(steps[0] / 100)
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
})

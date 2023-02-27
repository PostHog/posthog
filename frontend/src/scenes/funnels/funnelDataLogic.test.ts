import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { teamLogic } from 'scenes/teamLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from './funnelDataLogic'

import { FunnelVizType, InsightLogicProps, InsightModel, InsightType } from '~/types'
import { FunnelsQuery, NodeKind } from '~/queries/schema'
import {
    funnelResult,
    funnelResultWithBreakdown,
    funnelResultWithMultiBreakdown,
    funnelResultTimeToConvert,
} from './__mocks__/funnelDataLogicMocks'

describe('funnelDataLogic', () => {
    const insightProps: InsightLogicProps = {
        dashboardItemId: undefined,
    }
    let logic: ReturnType<typeof funnelDataLogic.build>
    let builtInsightLogic: ReturnType<typeof insightLogic.build>

    beforeEach(() => {
        initKeaTests(false)
    })

    async function initFunnelDataLogic(): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()

        builtInsightLogic = insightLogic(insightProps)
        builtInsightLogic.mount()
        await expectLogic(insightLogic).toFinishAllListeners()

        logic = funnelDataLogic(insightProps)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('funnel viz types', () => {
        beforeEach(async () => {
            await initFunnelDataLogic()
        })

        it('with non-funnel insight', async () => {
            await expectLogic(logic).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.TrendsQuery }),
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
                    funnel_viz_type: FunnelVizType.Steps,
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
                    funnel_viz_type: FunnelVizType.TimeToConvert,
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
                    funnel_viz_type: FunnelVizType.Trends,
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
        beforeEach(async () => {
            await initFunnelDataLogic()
        })

        it('with non-funnel insight', async () => {
            await expectLogic(logic).toMatchValues({
                querySource: expect.objectContaining({ kind: NodeKind.TrendsQuery }),
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

    /**
     * We set insightLogic.insight via a call to setInsight for data exploration,
     * in future we should use the response of dataNodeLogic via a connected
     * insightDataLogic.
     */
    describe('based on insightLogic', () => {
        beforeEach(async () => {
            await initFunnelDataLogic()
        })

        describe('results', () => {
            it('with non-funnel insight', async () => {
                await expectLogic(logic).toMatchValues({
                    insight: expect.objectContaining({ filters: {} }),
                    results: [],
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
                    builtInsightLogic.actions.setInsight(insight, {})
                }).toMatchValues({
                    results: funnelResult.result,
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
                    builtInsightLogic.actions.setInsight(insight, {})
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

            it('with multi breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResultWithMultiBreakdown.result,
                }

                await expectLogic(logic, () => {
                    builtInsightLogic.actions.setInsight(insight, {})
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
                        funnel_viz_type: FunnelVizType.TimeToConvert,
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
                    builtInsightLogic.actions.setInsight(insight, {})
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
                    builtInsightLogic.actions.setInsight(insight, {})
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
                    builtInsightLogic.actions.setInsight(insight, {})
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
                    builtInsightLogic.actions.setInsight(insight, {})
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
                    builtInsightLogic.actions.setInsight(insight, {})
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
                    builtInsightLogic.actions.setInsight(insight, {})
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
                    builtInsightLogic.actions.setInsight(insight, {})
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

        describe('flattenedStepsByBreakdown', () => {
            it('for standard funnel', async () => {
                const insight: Partial<InsightModel> = {
                    filters: {
                        insight: InsightType.FUNNELS,
                    },
                    result: funnelResult.result,
                }

                await expectLogic(logic, () => {
                    builtInsightLogic.actions.setInsight(insight, {})
                }).toMatchValues({
                    flattenedStepsByBreakdown: [
                        { rowKey: 'steps-meta' },
                        { rowKey: 'graph' },
                        { rowKey: 'table-header' },
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
                    builtInsightLogic.actions.setInsight(insight, {})
                }).toMatchValues({
                    flattenedStepsByBreakdown: [
                        { rowKey: 'steps-meta' },
                        { rowKey: 'graph' },
                        { rowKey: 'table-header' },
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
                    builtInsightLogic.actions.setInsight(insight, {})
                }).toMatchValues({
                    flattenedStepsByBreakdown: [
                        { rowKey: 'steps-meta' },
                        { rowKey: 'graph' },
                        { rowKey: 'table-header' },
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
    })
})

import { expectLogic, truth } from 'kea-test-utils'
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
                    ]),
                })
            })
        })
    })
})

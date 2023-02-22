import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'

import { teamLogic } from 'scenes/teamLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from './funnelDataLogic'

import { FunnelVizType, InsightLogicProps, InsightModel } from '~/types'
import { FunnelsQuery, NodeKind } from '~/queries/schema'

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

            it('with breakdown', async () => {
                const insight: Partial<InsightModel> = {
                    result: { a: 1 },
                }

                await expectLogic(logic, () => {
                    builtInsightLogic.actions.setInsight(insight, {})
                }).toMatchValues({
                    insight: { b: 5 },
                })
            })
        })

        describe('steps', () => {})
    })
})

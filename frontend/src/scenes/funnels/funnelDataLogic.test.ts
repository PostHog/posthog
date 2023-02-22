import { funnelDataLogic } from './funnelDataLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { FunnelVizType, InsightLogicProps } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { FunnelsQuery, NodeKind } from '~/queries/schema'

describe('funnelDataLogic', () => {
    let logic: ReturnType<typeof funnelDataLogic.build>

    beforeEach(() => {
        initKeaTests(false)
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
    }

    async function initFunnelDataLogic(props: InsightLogicProps = defaultProps): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = funnelDataLogic(props)
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
})

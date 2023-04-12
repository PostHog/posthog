import { funnelLogic } from './funnelLogic'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AvailableFeature, InsightLogicProps, InsightShortId, InsightType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { useMocks } from '~/mocks/jest'
import { useAvailableFeatures } from '~/mocks/features'
import api from 'lib/api'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

jest.mock('scenes/trends/persons-modal/PersonsModal')

const Insight123 = '123' as InsightShortId

const funnelResults = [
    {
        action_id: '$pageview',
        count: 19,
        name: '$pageview',
        order: 0,
        type: 'events',
    },
    {
        action_id: '$pageview',
        count: 7,
        name: '$pageview',
        order: 1,
        type: 'events',
    },
    {
        action_id: '$pageview',
        count: 4,
        name: '$pageview',
        order: 2,
        type: 'events',
    },
]

describe('funnelLogic', () => {
    let logic: ReturnType<typeof funnelLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.CORRELATION_ANALYSIS, AvailableFeature.GROUP_ANALYTICS])
        useMocks({
            get: {
                '/api/projects/:team/insights/': {
                    results: [{}],
                },
                '/api/projects/:team/insights/:id/': {},
                '/api/projects/:team/groups_types/': [],
            },
            post: {
                '/api/projects/:team/insights/funnel/': {
                    result: funnelResults,
                },
            },
        })
        initKeaTests(false)
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
        cachedInsight: {
            short_id: undefined,
            filters: {
                insight: InsightType.FUNNELS,
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
            },
            result: null,
        },
    }

    async function initFunnelLogic(props: InsightLogicProps = defaultProps): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        userLogic.mount()
        await expectLogic(userLogic).toFinishAllListeners()
        logic = funnelLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('core assumptions', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })

        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([
                eventUsageLogic,
                insightLogic({ dashboardItemId: undefined }),
                preflightLogic,
            ])
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        })

        it('sets filters after load if valid', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadResults'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        short_id: undefined,
                        filters: {
                            insight: InsightType.FUNNELS,
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        result: null,
                    }),
                    filters: {
                        insight: InsightType.FUNNELS,
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    isFunnelWithEnoughSteps: true,
                })
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        filters: {
                            insight: InsightType.FUNNELS,
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        result: expect.arrayContaining([expect.objectContaining({ count: 19 })]),
                    }),
                    filters: {
                        insight: InsightType.FUNNELS,
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    isFunnelWithEnoughSteps: true,
                })
        })
    })

    describe('isFunnelWithEnoughSteps', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })

        it('sets it properly', () => {
            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [] })
            }).toMatchValues({ isFunnelWithEnoughSteps: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({})
            }).toMatchValues({ isFunnelWithEnoughSteps: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [{}, {}] })
            }).toMatchValues({ isFunnelWithEnoughSteps: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}, {}] })
            }).toMatchValues({ isFunnelWithEnoughSteps: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}], actions: [{ from: 'previous isFunnelWithEnoughSteps test' }] })
            }).toMatchValues({ isFunnelWithEnoughSteps: true })
        })
    })

    it("load results, don't send breakdown if old visualisation is shown", async () => {
        jest.spyOn(api, 'createResponse')
        await initFunnelLogic()

        // wait for clickhouse features to be enabled, otherwise this won't call "loadResults"
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setFilters({
                actions: [],
                events: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                    { id: '$pageview', order: 2 },
                ],
                breakdown: '$active_feature_flags',
            })
        })
            .toDispatchActions(['setFilters', 'loadResults', 'loadResultsSuccess'])
            .toMatchValues({
                apiParams: expect.objectContaining({
                    actions: [],
                    events: [
                        { id: '$pageview', order: 0 },
                        { id: '$pageview', order: 1 },
                        { id: '$pageview', order: 2 },
                    ],
                    breakdown: undefined,
                    breakdown_type: undefined,
                }),
            })

        expect(api.createResponse).toHaveBeenNthCalledWith(
            2,
            `api/projects/${MOCK_TEAM_ID}/insights/funnel/`,
            expect.objectContaining({
                actions: [],
                events: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                    { id: '$pageview', order: 2 },
                ],
                breakdown: undefined,
                breakdown_type: undefined,
                insight: 'FUNNELS',
            }),
            expect.anything()
        )
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelLogic(props)
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: InsightType.FUNNELS, events: [{ id: 42 }] })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.events?.[0]?.id === 42,
                ])
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })

        it('insightLogic.setFilters updates filters', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({ insight: InsightType.FUNNELS, events: [{ id: 42 }] })
            })
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })
    })

    describe('it opens the PersonsModal', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelLogic(props)
        })

        test('openPersonsModalForStep calls openPersonsModal', async () => {
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            logic.actions.openPersonsModalForStep({
                step: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                },
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith({
                title: expect.any(Object),
                url: '/some/people/url?funnel_step=2', // Positive funnel_step and no funnel_step_breakdown
            })
        })

        test('openPersonsModalForSeries calls openPersonsModal', async () => {
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            logic.actions.openPersonsModalForSeries({
                series: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=Latvia',
                    droppedOffFromPrevious: 0,
                    conversionRates: {
                        fromPrevious: 1,
                        total: 1,
                        fromBasisStep: 1,
                    },
                },
                step: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                },
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith({
                title: expect.any(Object),
                url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia', // Series funnel_step_breakdown included
            })
        })
    })

    describe('funnel simple vs. advanced mode', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })

        it("toggleAdvancedMode() doesn't trigger a load result", async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleAdvancedMode()
            })
                .toDispatchActions(['toggleAdvancedMode', 'setFilters'])
                .toNotHaveDispatchedActions([
                    insightLogic({ dashboardItemId: Insight123 }).actionCreators.loadResults(),
                ])
        })
    })
})

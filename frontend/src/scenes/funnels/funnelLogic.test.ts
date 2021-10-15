import { funnelLogic } from './funnelLogic'
import { api, defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { funnelsModel } from '~/models/funnelsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { ViewType } from '~/types'

jest.mock('lib/api')

describe('funnelLogic', () => {
    let logic: ReturnType<typeof funnelLogic.build>

    mockAPI(async (url) => {
        if (url.pathname === 'api/insight/funnel/') {
            return {
                is_cached: true,
                last_refresh: '2021-09-16T13:41:41.297295Z',
                result: ['result from api'],
                type: 'Funnel',
            }
        } else if (url.pathname.startsWith('api/insight')) {
            return { results: [], next: null }
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: funnelLogic,
        props: {
            dashboardItemId: undefined,
            filters: {
                insight: ViewType.FUNNELS,
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
            },
        },
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([
                eventUsageLogic,
                insightLogic({ dashboardItemId: undefined }),
                insightHistoryLogic,
                preflightLogic,
                funnelsModel,
            ])
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(funnelsModel).toDispatchActions(['loadFunnelsSuccess'])
        })

        it('has clickhouse enabled once preflight loads', async () => {
            await expectLogic()
                .toDispatchActions(preflightLogic, ['loadPreflight'])
                .toMatchValues(logic, {
                    clickhouseFeaturesEnabled: false,
                })
                .toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
                .toMatchValues(logic, {
                    clickhouseFeaturesEnabled: true,
                })
        })

        it('sets filters after load if valid', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadResults'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        id: undefined,
                        filters: {},
                        result: null,
                    }),
                    filters: {
                        insight: ViewType.FUNNELS,
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    areFiltersValid: true,
                })
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        filters: {
                            insight: ViewType.FUNNELS,
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        result: ['result from api'],
                    }),
                    filters: {
                        insight: ViewType.FUNNELS,
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    areFiltersValid: true,
                })
        })
    })

    describe('areFiltersValid', () => {
        beforeEach(async () => await expectLogic(logic).toFinishAllListeners())

        it('sets it properly', () => {
            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [] })
            }).toMatchValues({ areFiltersValid: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({})
            }).toMatchValues({ areFiltersValid: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [{}, {}] })
            }).toMatchValues({ areFiltersValid: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}, {}] })
            }).toMatchValues({ areFiltersValid: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}], actions: [{ from: 'previous areFiltersValid test' }] })
            }).toMatchValues({ areFiltersValid: true })
        })
    })

    it("load results, don't send breakdown if old visualisation is shown", async () => {
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

        expect(api.create).toBeCalledWith(
            'api/insight/funnel/?',
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
                interval: 'day',
            })
        )
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: 123 }
        initKeaTestLogic({
            logic: funnelLogic,
            props,
            onLogic: (l) => (logic = l),
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{ id: 42 }] })
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
                insightLogic(props).actions.setFilters({ events: [{ id: 42 }] })
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
})

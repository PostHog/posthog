import { BuiltLogic } from 'kea'
import { funnelLogic, FunnelLogicProps } from './funnelLogic'
import { funnelLogicType } from './funnelLogicType'
import { api, mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { funnelsModel } from '~/models/funnelsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { FunnelAPIResponse, PropertyOperator } from '~/types'

jest.mock('lib/api')

describe('funnelLogic', () => {
    let logic: BuiltLogic<funnelLogicType<FunnelLogicProps>>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/insight/funnel/') {
            return {
                is_cached: true,
                last_refresh: '2021-09-16T13:41:41.297295Z',
                result: ['result from api'],
                type: 'Funnel',
            }
        } else if (pathname.startsWith('api/insight')) {
            return { results: [], next: null }
        } else if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else if (
            ['api/action/', 'api/projects/@current/event_definitions/', 'api/users/@me/', 'api/dashboard'].includes(
                pathname
            )
        ) {
            return { results: [] }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    initKeaTestLogic({
        logic: funnelLogic,
        props: {
            filters: {
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
                insightLogic,
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

        it('sets filters in rawResults after load if valid', async () => {
            await expectLogic(logic)
                .toMatchValues({
                    rawResults: {
                        filters: {},
                        results: [],
                    },
                    filters: {
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    areFiltersValid: true,
                })
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    rawResults: {
                        filters: {
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        results: ['result from api'],
                    },
                    filters: {
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
            // insightLogic gets called via insightHistoryLogic to createInsights (and save the insights)
            // but it's not automatically mounted. TODO: what to do?
            insightLogic.mount()

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

    it("Load results, don't send breakdown if old visualisation is shown", async () => {
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

    describe('as dashboard item', () => {
        describe('props with filters and cached results', () => {
            initKeaTestLogic({
                logic: funnelLogic,
                props: {
                    dashboardItemId: 123,
                    cachedResults: ['cached result'],
                    filters: {
                        events: [{ id: 2 }, { id: 3 }],
                        properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('no query to load results', async () => {
                await expectLogic(logic)
                    .toMatchValues({
                        areFiltersValid: true,
                        results: ['cached result'],
                        filters: expect.objectContaining({
                            events: [{ id: 2 }, { id: 3 }],
                            properties: [expect.objectContaining({ type: 'lol' })],
                        }),
                    })
                    .toDispatchActions(['loadResultsSuccess']) // this took the cached results
                    .toMatchValues({
                        results: ['cached result'], // should not have changed
                        filters: expect.objectContaining({
                            events: [{ id: 2 }, { id: 3 }],
                            properties: [expect.objectContaining({ value: 'lol' })],
                        }),
                    })
            })
        })

        describe('props with filters, no cached results', () => {
            initKeaTestLogic({
                logic: funnelLogic,
                props: {
                    dashboardItemId: 123,
                    cachedResults: undefined,
                    filters: {
                        events: [{ id: 2 }, { id: 3 }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadResultsSuccess'])
                    .toMatchValues({
                        results: ['result from api'],
                        filters: expect.objectContaining({
                            events: [{ id: 2 }, { id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
            })

            it('setCachedResults sets results directly', async () => {
                await expectLogic(logic).toDispatchActions(['loadResultsSuccess'])

                logic.actions.setCachedResults(
                    {
                        events: [{ id: 2 }, { id: 3 }],
                        properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                    },
                    ['cached result' as any] as FunnelAPIResponse
                )

                await expectLogic(logic)
                    .toDispatchActions(['setCachedResults', 'setCachedResultsSuccess'])
                    .toMatchValues({
                        results: ['cached result'],
                        filters: expect.objectContaining({
                            events: [{ id: 2 }, { id: 3 }],
                            properties: [expect.objectContaining({ type: 'lol' })],
                        }),
                    })
            })
        })
    })
})

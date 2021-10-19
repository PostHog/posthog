import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { insightLogic } from './insightLogic'
import { AvailableFeature, PropertyOperator, ViewType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { combineUrl, router } from 'kea-router'

jest.mock('lib/api')

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    mockAPI(async (url) => {
        const { pathname, searchParams } = url
        const throwAPIError = (): void => {
            throw { status: 0, statusText: 'error from the API' }
        }
        if (['api/insight/42', 'api/insight/43'].includes(pathname)) {
            return {
                result: pathname === 'api/insight/42' ? ['result from api'] : null,
                id: pathname === 'api/insight/42' ? 42 : 43,
                filters: {
                    insight: ViewType.TRENDS,
                    events: [{ id: 3 }],
                    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                },
            }
        } else if (['api/insight/44'].includes(pathname)) {
            throwAPIError()
        } else if (
            ['api/insight', 'api/insight/session/', 'api/insight/trend/', 'api/insight/funnel/'].includes(pathname)
        ) {
            if (searchParams?.events?.[0]?.throw) {
                throwAPIError()
            }
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url, { availableFeatures: [AvailableFeature.DASHBOARD_COLLABORATION] })
    })

    it('requires props', () => {
        expect(() => {
            insightLogic()
        }).toThrow('Must init with dashboardItemId, even if undefined')
    })

    describe('when there is no props id', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: {
                dashboardItemId: undefined,
            },
            onLogic: (l) => (logic = l),
        })

        it('has the key set to "new"', () => {
            expect(logic.key).toEqual('new')
        })
    })

    describe('analytics', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: { dashboardItemId: undefined, filters: { insight: 'TRENDS' } },
            onLogic: (l) => (logic = l),
        })

        it('reports insight changes on setFilter', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: 'FUNNELS' })
            }).toDispatchActions([
                eventUsageLogic.actionCreators.reportInsightViewed({ insight: 'FUNNELS' }, true, false, 0, {
                    changed_insight: 'TRENDS',
                }),
            ])
        })
    })

    describe('as dashboard item', () => {
        describe('props with filters and cached results', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: ['cached result'],
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 2 }],
                        properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('has the key set to the id', () => {
                expect(logic.key).toEqual(42)
            })
            it('no query to load results', async () => {
                await expectLogic(logic)
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: ['cached result'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 2 }],
                            properties: [expect.objectContaining({ type: 'lol' })],
                        }),
                    })
                    .toNotHaveDispatchedActions(['loadResultsSuccess']) // this took the cached results
            })
        })

        describe('props with filters, no cached results', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3 }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsSuccess'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: ['result from api'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
                    .toDispatchActions(['updateInsight', 'updateInsightSuccess'])
            })
        })

        describe('props with filters, no cached results, error from API', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsFailure'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: null }),
                        filters: expect.objectContaining({
                            events: [expect.objectContaining({ id: 3 })],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })

        describe('props with filters, no cached results, respects doNotLoad', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                    doNotLoad: true,
                },
                onLogic: (l) => (logic = l),
            })

            it('does not make a query', async () => {
                await expectLogic(logic)
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: null }),
                        filters: expect.objectContaining({
                            events: [expect.objectContaining({ id: 3 })],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })

        describe('props with no filters, no cached results, results from API', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: undefined,
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightSuccess'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: ['result from api'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
                    .toNotHaveDispatchedActions(['loadResults']) // does not fetch results as there was no filter
            })
        })

        describe('props with no filters, no cached results, no results from API', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 43, // 43 --> result: null
                    cachedResults: undefined,
                    filters: undefined,
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightSuccess'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 43, result: null }),
                        filters: expect.objectContaining({
                            events: [{ id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
                    .toDispatchActions(['loadResults', 'loadResultsSuccess'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 43, result: ['result from api'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
            })
        })

        describe('props with no filters, no cached results, API throws', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 44, // 44 --> result: throws
                    cachedResults: undefined,
                    filters: undefined,
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightFailure'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 44, result: null, filters: {} }),
                        filters: {},
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })
    })

    describe('reacts to the URL', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: {
                syncWithUrl: true,
                dashboardItemId: undefined,
            },
            onLogic: (l) => (logic = l),
        })

        beforeEach(async () => await expectLogic(logic).toFinishAllListeners())

        it('sets filters from the URL', async () => {
            const url = combineUrl('/insights', { insight: 'TRENDS', interval: 'minute' }).url
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url), 'setFilters'])
                .toMatchValues({
                    filters: expect.objectContaining({ insight: 'TRENDS', interval: 'minute' }),
                })

            // setting the same URL twice doesn't call `setFilters`
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url)])
                .toNotHaveDispatchedActions(['setFilters'])
                .toMatchValues({
                    filters: expect.objectContaining({ insight: 'TRENDS', interval: 'minute' }),
                })

            // calls when the values changed
            const url2 = combineUrl('/insights', { insight: 'TRENDS', interval: 'week' }).url
            router.actions.push(url2)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url2), 'setFilters'])
                .toMatchValues({
                    filters: expect.objectContaining({ insight: 'TRENDS', interval: 'week' }),
                })
        })

        it('takes the dashboardItemId from the URL', async () => {
            const url = combineUrl('/insights', { insight: 'TRENDS' }, { fromItem: 42 }).url
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url), 'loadInsight', 'loadInsightSuccess'])
                .toNotHaveDispatchedActions(['loadResults'])
                .toMatchValues({
                    filters: expect.objectContaining({ insight: 'TRENDS' }),
                    insight: expect.objectContaining({ id: 42, result: ['result from api'] }),
                })

            // changing the ID, does not query twice
            router.actions.push(combineUrl('/insights', { insight: 'FUNNELS' }, { fromItem: 43 }).url)
            await expectLogic(logic)
                .toDispatchActions(['loadInsight', 'setFilters', 'loadResults', 'loadInsightSuccess'])
                .toMatchValues({
                    filters: expect.objectContaining({ insight: 'FUNNELS' }),
                    insight: expect.objectContaining({ id: 43, result: null }),
                })
                .toNotHaveDispatchedActions(['loadResults']) // don't load twice!
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    insight: expect.objectContaining({ id: 43, result: ['result from api'] }),
                })
        })

        it('sets the URL when changing filters', async () => {
            logic.actions.setFilters({ insight: 'TRENDS', interval: 'minute' })
            await expectLogic()
                .toDispatchActions(logic, [logic.actionCreators.setFilters({ insight: 'TRENDS', interval: 'minute' })])
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: expect.objectContaining({ interval: 'minute' }) })

            // no change in filters, doesn't change the URL
            logic.actions.setFilters({ insight: 'TRENDS', interval: 'minute' })
            await expectLogic()
                .toDispatchActions(logic, [logic.actionCreators.setFilters({ insight: 'TRENDS', interval: 'minute' })])
                .toNotHaveDispatchedActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: expect.objectContaining({ interval: 'minute' }) })

            logic.actions.setFilters({ insight: 'TRENDS', interval: 'month' })
            await expectLogic()
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, {
                    searchParams: expect.objectContaining({ insight: 'TRENDS', interval: 'month' }),
                })
        })
    })
})

import { defaultAPIMocks, MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { insightLogic } from './insightLogic'
import { AvailableFeature, InsightShortId, InsightType, ItemMode, PropertyOperator } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { combineUrl, router } from 'kea-router'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'

jest.mock('lib/api')

const API_FILTERS = {
    insight: InsightType.TRENDS as InsightType,
    events: [{ id: 3 }],
    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
}

const Insight12 = '12' as InsightShortId
const Insight42 = '42' as InsightShortId
const Insight43 = '43' as InsightShortId
const Insight44 = '44' as InsightShortId
const Insight500 = '500' as InsightShortId

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>
    beforeEach(initKeaTests)

    mockAPI(async (url) => {
        const { pathname, searchParams, method, data } = url
        const throwAPIError = (): void => {
            throw { status: 0, statusText: 'error from the API' }
        }
        if (
            [
                `api/projects/${MOCK_TEAM_ID}/insights`,
                `api/projects/${MOCK_TEAM_ID}/insights/42`,
                `api/projects/${MOCK_TEAM_ID}/insights/43`,
                `api/projects/${MOCK_TEAM_ID}/insights/44`,
            ].includes(pathname)
        ) {
            return {
                result: pathname.endsWith('42') ? ['result from api'] : null,
                id: pathname.endsWith('42') ? 42 : 43,
                short_id: pathname.endsWith('42') ? Insight42 : Insight43,
                filters: data?.filters || API_FILTERS,
            }
        } else if (pathname === 'api/projects/997/insights/' && url.searchParams.short_id) {
            if (url.searchParams.short_id === 500) {
                throwAPIError()
            }

            return {
                results: [
                    {
                        result: parseInt(url.searchParams.short_id) === 42 ? ['result from api'] : null,
                        id: parseInt(url.searchParams.short_id),
                        short_id: url.searchParams.short_id.toString(),
                        filters: data?.filters || API_FILTERS,
                    },
                ],
            }
        } else if ([`api/projects/${MOCK_TEAM_ID}/dashboards/33/`].includes(pathname)) {
            return {
                id: 33,
                filters: {},
                items: [
                    {
                        id: 42,
                        short_id: Insight42,
                        result: 'result!',
                        filters: { insight: InsightType.TRENDS, interval: 'month' },
                        tags: ['bla'],
                    },
                ],
            }
        } else if ([`api/projects/${MOCK_TEAM_ID}/insights/500`].includes(pathname)) {
            throwAPIError()
        } else if (pathname === 'api/projects/997/insights/' && url.searchParams.saved) {
            return {
                results: [
                    { id: 42, short_id: Insight42, result: ['result 42'], filters: API_FILTERS },
                    { id: 43, short_id: Insight43, result: ['result 43'], filters: API_FILTERS },
                ],
            }
        } else if (method === 'create' && pathname === `api/projects/${MOCK_TEAM_ID}/insights/`) {
            return { id: 12, short_id: Insight12, name: data?.name }
        } else if (
            [
                `api/projects/${MOCK_TEAM_ID}/insights`,
                `api/projects/${MOCK_TEAM_ID}/insights/session/`,
                `api/projects/${MOCK_TEAM_ID}/insights/trend/`,
                `api/projects/${MOCK_TEAM_ID}/insights/path/`,
                `api/projects/${MOCK_TEAM_ID}/insights/path`,
                `api/projects/${MOCK_TEAM_ID}/insights/funnel/`,
                `api/projects/${MOCK_TEAM_ID}/insights/retention/`,
            ].includes(pathname)
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
        it('has the key set to "new"', () => {
            logic = insightLogic({
                dashboardItemId: undefined,
            })
            expect(logic.key).toEqual('new')
        })
    })

    describe('analytics', () => {
        it('reports insight changes on setFilter', async () => {
            logic = insightLogic({
                dashboardItemId: undefined,
                filters: { insight: InsightType.TRENDS },
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: InsightType.FUNNELS })
            }).toDispatchActions([
                eventUsageLogic.actionCreators.reportInsightViewed(
                    { insight: InsightType.FUNNELS },
                    ItemMode.View,
                    true,
                    false,
                    0,
                    {
                        changed_insight: InsightType.TRENDS,
                    }
                ),
            ])
        })
    })

    describe('as dashboard item', () => {
        describe('props with filters and cached results', () => {
            beforeEach(() => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedResults: ['cached result'],
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 2 }],
                        properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                    },
                })
                logic.mount()
            })

            it('has the key set to the id', () => {
                expect(logic.key).toEqual('42')
            })
            it('no query to load results', async () => {
                await expectLogic(logic)
                    .toMatchValues({
                        insight: partial({ short_id: Insight42, result: ['cached result'] }),
                        filters: partial({
                            events: [{ id: 2 }],
                            properties: [partial({ type: 'lol' })],
                        }),
                    })
                    .toNotHaveDispatchedActions(['loadResultsSuccess']) // this took the cached results
            })
        })

        describe('props with filters, no cached results', () => {
            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedResults: undefined,
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 3 }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsSuccess'])
                    .toMatchValues({
                        insight: partial({ short_id: Insight42, result: ['result from api'] }),
                        filters: partial({
                            events: [{ id: 3 }],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
                    .delay(1)
                    // do not override the insight if querying with different filters
                    .toNotHaveDispatchedActions(['updateInsight', 'updateInsightSuccess'])
            })
        })

        describe('props with filters, no cached results, error from API', () => {
            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedResults: undefined,
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsFailure'])
                    .toMatchValues({
                        insight: partial({ short_id: Insight42, result: null }),
                        filters: partial({
                            events: [partial({ id: 3 })],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })

        describe('props with filters, no cached results, respects doNotLoad', () => {
            it('does not make a query', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedResults: undefined,
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                    doNotLoad: true,
                })
                logic.mount()

                await expectLogic(logic)
                    .toMatchValues({
                        insight: partial({ short_id: Insight42, result: null }),
                        filters: partial({
                            events: [partial({ id: 3 })],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })

        describe('props with no filters, no cached results, results from API', () => {
            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedResults: undefined,
                    filters: undefined,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightSuccess'])
                    .toMatchValues({
                        insight: partial({ short_id: Insight42, result: ['result from api'] }),
                        filters: partial({
                            events: [{ id: 3 }],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
                    .toNotHaveDispatchedActions(['loadResults']) // does not fetch results as there was no filter
            })
        })

        describe('props with no filters, no cached results, no results from API', () => {
            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight43, // 43 --> result: null
                    cachedResults: undefined,
                    filters: undefined,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightSuccess'])
                    .toMatchValues({
                        insight: partial({ id: 43, result: null }),
                        filters: partial({
                            events: [{ id: 3 }],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
                    .toDispatchActions(['loadResults', 'loadResultsSuccess'])
                    .toMatchValues({
                        insight: partial({ id: 43, result: ['result from api'] }),
                        filters: partial({
                            events: [{ id: 3 }],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
            })
        })

        describe('props with no filters, no cached results, API throws', () => {
            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight500, // 500 --> result: throws
                    cachedResults: undefined,
                    filters: undefined,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightFailure'])
                    .toMatchValues({
                        insight: partial({ short_id: '500', result: null, filters: {} }),
                        filters: {},
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })
    })

    describe('syncWithUrl: true persists state in the URL', () => {
        beforeEach(async () => {
            logic = insightLogic({
                syncWithUrl: true,
                dashboardItemId: Insight44,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().clearHistory()
        })

        it('redirects when opening /insight/new', async () => {
            router.actions.push(urls.insightEdit(Insight42))
            await expectLogic(router)
                .delay(1)
                .toMatchValues({
                    location: partial({ pathname: urls.insightEdit(Insight42) }),
                    searchParams: partial({ insight: 'TRENDS' }),
                })

            router.actions.push(urls.insightNew({ insight: InsightType.FUNNELS }))
            await expectLogic(router)
                .delay(1)
                .toMatchValues({
                    location: partial({ pathname: urls.insightEdit(Insight43) }),
                    searchParams: partial({ insight: 'FUNNELS' }),
                })
        })

        it('sets filters from the URL', async () => {
            const url = urls.insightEdit(Insight44, { insight: InsightType.TRENDS, interval: 'minute' })
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url), 'setFilters'])
                .toMatchValues({
                    filters: partial({ insight: InsightType.TRENDS, interval: 'minute' }),
                })

            // setting the same URL twice doesn't call `setFilters`
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url)])
                .toNotHaveDispatchedActions(['setFilters'])
                .toMatchValues({
                    filters: partial({ insight: InsightType.TRENDS, interval: 'minute' }),
                })

            // calls when the values changed
            const url2 = urls.insightEdit(Insight44, { insight: InsightType.TRENDS, interval: 'week' })
            router.actions.push(url2)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url2), 'setFilters'])
                .toMatchValues({
                    filters: partial({ insight: InsightType.TRENDS, interval: 'week' }),
                })
        })

        it('takes the dashboardItemId from the URL', async () => {
            const url = urls.insightView(Insight42, { insight: InsightType.TRENDS })
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url), 'loadInsight', 'loadInsightSuccess'])
                .toNotHaveDispatchedActions(['loadResults'])
                .toMatchValues({
                    filters: partial({ insight: InsightType.TRENDS }),
                    insight: partial({ short_id: Insight42, result: ['result from api'] }),
                })

            // changing the ID, does not query twice
            router.actions.push(urls.insightView(Insight43, { insight: InsightType.FUNNELS }))
            await expectLogic(logic)
                .toDispatchActions(['loadInsight', 'setFilters', 'loadResults', 'loadInsightSuccess'])
                .toMatchValues({
                    filters: partial({ insight: InsightType.FUNNELS }),
                    insight: partial({ id: 43, result: null }),
                })
                .toNotHaveDispatchedActions(['loadResults']) // don't load twice!
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    insight: partial({ id: 43, result: ['result from api'] }),
                })
        })

        it('sets the URL when changing filters', async () => {
            // make sure we're on the right page
            router.actions.push(urls.insightNew())
            await expectLogic(router).toDispatchActions(['push', 'locationChanged', 'replace', 'locationChanged'])

            logic.actions.setFilters({ insight: InsightType.TRENDS, interval: 'minute' })
            await expectLogic()
                .toDispatchActions(logic, [
                    logic.actionCreators.setFilters({ insight: InsightType.TRENDS, interval: 'minute' }),
                ])
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: partial({ interval: 'minute' }) })

            // no change in filters, doesn't change the URL
            logic.actions.setFilters({ insight: InsightType.TRENDS, interval: 'minute' })
            await expectLogic()
                .toDispatchActions(logic, [
                    logic.actionCreators.setFilters({ insight: InsightType.TRENDS, interval: 'minute' }),
                ])
                .toNotHaveDispatchedActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: partial({ interval: 'minute' }) })

            logic.actions.setFilters({ insight: InsightType.TRENDS, interval: 'month' })
            await expectLogic(router)
                .toDispatchActions(['replace', 'locationChanged'])
                .toMatchValues({
                    searchParams: partial({ insight: InsightType.TRENDS, interval: 'month' }),
                })
        })

        it('persists edit mode in the url', async () => {
            const viewUrl = combineUrl(urls.insightView(Insight42, cleanFilters({ insight: InsightType.TRENDS })))
            const editUrl = combineUrl(urls.insightEdit(Insight42, cleanFilters({ insight: InsightType.TRENDS })))

            router.actions.push(viewUrl.url)
            await expectLogic(logic)
                .toNotHaveDispatchedActions(['setInsightMode'])
                .toDispatchActions(['loadInsightSuccess'])
                .toMatchValues({
                    filters: partial({ insight: InsightType.TRENDS }),
                    insight: partial({ short_id: Insight42, result: ['result from api'] }),
                    insightMode: ItemMode.View,
                })

            router.actions.push(editUrl.url)
            await expectLogic(logic)
                .toDispatchActions([
                    ({ type, payload }) =>
                        type === logic.actionTypes.setFilters && payload.insightMode === ItemMode.Edit,
                ])
                .toMatchValues({
                    insightMode: ItemMode.Edit,
                })

            logic.actions.setInsightMode(ItemMode.View, null)
            expectLogic(router).toMatchValues({
                location: partial({ pathname: viewUrl.pathname, search: viewUrl.search, hash: viewUrl.hash }),
            })

            logic.actions.setInsightMode(ItemMode.Edit, null)
            expectLogic(router).toMatchValues({
                location: partial({ pathname: editUrl.pathname, search: editUrl.search, hash: editUrl.hash }),
            })
        })
    })

    describe('takes data from other logics if available', () => {
        it('dashboardLogic', async () => {
            // 1. the URL must have the dashboard and insight IDs
            router.actions.push(urls.insightView(Insight42), {}, { fromDashboard: 33 })

            // 2. the dashboard is mounted
            const dashLogic = dashboardLogic({ id: 33 })
            dashLogic.mount()
            await expectLogic(dashLogic).toDispatchActions(['loadDashboardItemsSuccess'])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42 })
            logic.mount()

            // 4. verify it didn't make any API calls
            await expectLogic(logic)
                .toDispatchActions(['setInsight'])
                .toNotHaveDispatchedActions(['setFilters', 'loadResults', 'loadInsight', 'updateInsight'])
                .toMatchValues({
                    insight: partial({
                        id: 42,
                        result: 'result!',
                        filters: { insight: InsightType.TRENDS, interval: 'month' },
                    }),
                })
        })

        it('savedInsightLogic', async () => {
            // 1. open saved insights
            router.actions.push(urls.savedInsights(), {}, {})
            savedInsightsLogic.mount()

            // 2. the insights are loaded
            await expectLogic(savedInsightsLogic).toDispatchActions(['loadInsights', 'loadInsightsSuccess'])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42 })
            logic.mount()

            // 4. verify it didn't make any API calls
            await expectLogic(logic)
                .toDispatchActions(['setInsight'])
                .toNotHaveDispatchedActions(['setFilters', 'loadResults', 'loadInsight', 'updateInsight'])
                .toMatchValues({
                    insight: partial({
                        id: 42,
                        result: ['result 42'],
                        filters: API_FILTERS,
                    }),
                })
        })
    })

    test('keeps saved filters', async () => {
        logic = insightLogic({
            dashboardItemId: Insight42,
            filters: { insight: InsightType.FUNNELS },
        })
        logic.mount()

        // `setFilters` only changes `filters`, does not change `savedFilters`
        await expectLogic(logic, () => {
            logic.actions.setFilters({ insight: InsightType.TRENDS })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedFilters: partial({ insight: InsightType.FUNNELS }),
            filtersChanged: true,
        })

        // results from search don't change anything
        await expectLogic(logic, () => {
            logic.actions.loadResultsSuccess({
                short_id: Insight42,
                filters: { insight: InsightType.PATHS },
            })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedFilters: partial({ insight: InsightType.FUNNELS }),
            filtersChanged: true,
        })

        // results from API GET and POST calls change saved filters
        await expectLogic(logic, () => {
            logic.actions.loadInsightSuccess({
                short_id: Insight42,
                filters: { insight: InsightType.PATHS },
            })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedFilters: partial({ insight: InsightType.PATHS }),
            filtersChanged: true,
        })
        await expectLogic(logic, () => {
            logic.actions.updateInsightSuccess({
                short_id: Insight42,
                filters: { insight: InsightType.RETENTION },
            })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedFilters: partial({ insight: InsightType.RETENTION }),
            filtersChanged: true,
        })

        // saving persists the in-flight filters
        await expectLogic(logic, () => {
            logic.actions.setFilters(API_FILTERS)
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            loadedFilters: partial({ insight: InsightType.TRENDS }),
            savedFilters: partial({ insight: InsightType.RETENTION }),
            filtersChanged: true,
        })

        await expectLogic(logic, () => {
            logic.actions.saveInsight()
        }).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            loadedFilters: partial({ insight: InsightType.TRENDS }),
            savedFilters: partial({ insight: InsightType.TRENDS }),
            filtersChanged: false,
        })
    })

    test('saveInsight and updateInsight reload the saved insights list', async () => {
        savedInsightsLogic.mount()
        logic = insightLogic({
            dashboardItemId: Insight42,
            filters: { insight: InsightType.FUNNELS },
        })
        logic.mount()

        logic.actions.saveInsight()
        await expectLogic(savedInsightsLogic).toDispatchActions(['loadInsights'])

        logic.actions.updateInsight({ filters: { insight: InsightType.FUNNELS } })
        await expectLogic(savedInsightsLogic).toDispatchActions(['loadInsights'])
    })

    test('save as new insight', async () => {
        const url = combineUrl('/insights/42', { insight: InsightType.FUNNELS }).url
        router.actions.push(url)
        savedInsightsLogic.mount()

        logic = insightLogic({
            dashboardItemId: Insight42,
            filters: { insight: InsightType.FUNNELS },
            savedFilters: { insight: InsightType.FUNNELS },
            syncWithUrl: true,
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.saveAsNamingSuccess('New Insight (copy)')
        })
            .toDispatchActions(['setInsight'])
            .toDispatchActions(savedInsightsLogic, ['loadInsights'])
            .toMatchValues({
                filters: partial({ insight: InsightType.FUNNELS }),
                insight: partial({ id: 12, short_id: Insight12, name: 'New Insight (copy)' }),
                filtersChanged: true,
                syncWithUrl: true,
            })

        await expectLogic(router)
            .toDispatchActions(['push', 'locationChanged'])
            .toMatchValues({
                location: partial({ pathname: '/insights/12/edit' }),
            })
    })
})

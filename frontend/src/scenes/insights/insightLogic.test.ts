import { defaultAPIMocks, MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { insightLogic } from './insightLogic'
import { AvailableFeature, InsightType, ItemMode, PropertyOperator, ViewType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { combineUrl, router } from 'kea-router'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

jest.mock('lib/api')

const API_FILTERS = {
    insight: ViewType.TRENDS as InsightType,
    events: [{ id: 3 }],
    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
}

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>
    beforeEach(initKeaTests)

    mockAPI(async (url) => {
        const { pathname, searchParams } = url
        const throwAPIError = (): void => {
            throw { status: 0, statusText: 'error from the API' }
        }
        if (
            [
                `api/projects/${MOCK_TEAM_ID}/insights/42`,
                `api/projects/${MOCK_TEAM_ID}/insights/43`,
                `api/projects/${MOCK_TEAM_ID}/insights/44`,
            ].includes(pathname)
        ) {
            return {
                result: pathname.endsWith('42') ? ['result from api'] : null,
                id: pathname.endsWith('42') ? 42 : 43,
                filters: API_FILTERS,
            }
        } else if ([`api/projects/${MOCK_TEAM_ID}/dashboards/33/`].includes(pathname)) {
            return {
                id: 33,
                filters: {},
                items: [
                    { id: 42, result: 'result!', filters: { insight: 'TRENDS', interval: 'month' }, tags: ['bla'] },
                ],
            }
        } else if ([`api/projects/${MOCK_TEAM_ID}/insights/500`].includes(pathname)) {
            throwAPIError()
        } else if (pathname === 'api/projects/997/insights/' && url.searchParams.saved) {
            return {
                results: [
                    { id: 42, result: ['result 42'], filters: API_FILTERS },
                    { id: 43, result: ['result 43'], filters: API_FILTERS },
                ],
            }
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
                filters: { insight: 'TRENDS' },
            })
            logic.mount()

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
            beforeEach(() => {
                logic = insightLogic({
                    dashboardItemId: 42,
                    cachedResults: ['cached result'],
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 2 }],
                        properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                    },
                })
                logic.mount()
            })

            it('has the key set to the id', () => {
                expect(logic.key).toEqual(42)
            })
            it('no query to load results', async () => {
                await expectLogic(logic)
                    .toMatchValues({
                        insight: partial({ id: 42, result: ['cached result'] }),
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
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3 }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsSuccess'])
                    .toMatchValues({
                        insight: partial({ id: 42, result: ['result from api'] }),
                        filters: partial({
                            events: [{ id: 3 }],
                            properties: [partial({ value: 'a' })],
                        }),
                    })
                    .toDispatchActions(['updateInsight', 'updateInsightSuccess'])
            })
        })

        describe('props with filters, no cached results, error from API', () => {
            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsFailure'])
                    .toMatchValues({
                        insight: partial({ id: 42, result: null }),
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
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                    doNotLoad: true,
                })
                logic.mount()

                await expectLogic(logic)
                    .toMatchValues({
                        insight: partial({ id: 42, result: null }),
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
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: undefined,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightSuccess'])
                    .toMatchValues({
                        insight: partial({ id: 42, result: ['result from api'] }),
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
                    dashboardItemId: 43, // 43 --> result: null
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
                    dashboardItemId: 500, // 500 --> result: throws
                    cachedResults: undefined,
                    filters: undefined,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightFailure'])
                    .toMatchValues({
                        insight: partial({ id: 500, result: null, filters: {} }),
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
                dashboardItemId: 44,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().clearHistory()
        })

        it('sets filters from the URL', async () => {
            const url = combineUrl('/insights', { insight: 'TRENDS', interval: 'minute' }).url
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url), 'setFilters'])
                .toMatchValues({
                    filters: partial({ insight: 'TRENDS', interval: 'minute' }),
                })

            // setting the same URL twice doesn't call `setFilters`
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url)])
                .toNotHaveDispatchedActions(['setFilters'])
                .toMatchValues({
                    filters: partial({ insight: 'TRENDS', interval: 'minute' }),
                })

            // calls when the values changed
            const url2 = combineUrl('/insights', { insight: 'TRENDS', interval: 'week' }).url
            router.actions.push(url2)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url2), 'setFilters'])
                .toMatchValues({
                    filters: partial({ insight: 'TRENDS', interval: 'week' }),
                })
        })

        it('takes the dashboardItemId from the URL', async () => {
            const url = combineUrl('/insights', { insight: 'TRENDS' }, { fromItem: 42 }).url
            router.actions.push(url)
            await expectLogic(logic)
                .toDispatchActions([router.actionCreators.push(url), 'loadInsight', 'loadInsightSuccess'])
                .toNotHaveDispatchedActions(['loadResults'])
                .toMatchValues({
                    filters: partial({ insight: 'TRENDS' }),
                    insight: partial({ id: 42, result: ['result from api'] }),
                })

            // changing the ID, does not query twice
            router.actions.push(combineUrl('/insights', { insight: 'FUNNELS' }, { fromItem: 43 }).url)
            await expectLogic(logic)
                .toDispatchActions(['loadInsight', 'setFilters', 'loadResults', 'loadInsightSuccess'])
                .toMatchValues({
                    filters: partial({ insight: 'FUNNELS' }),
                    insight: partial({ id: 43, result: null }),
                })
                .toNotHaveDispatchedActions(['loadResults']) // don't load twice!
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    insight: partial({ id: 43, result: ['result from api'] }),
                })
        })

        it('sets the URL when changing filters', async () => {
            logic.actions.setFilters({ insight: 'TRENDS', interval: 'minute' })
            await expectLogic()
                .toDispatchActions(logic, [logic.actionCreators.setFilters({ insight: 'TRENDS', interval: 'minute' })])
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: partial({ interval: 'minute' }) })

            // no change in filters, doesn't change the URL
            logic.actions.setFilters({ insight: 'TRENDS', interval: 'minute' })
            await expectLogic()
                .toDispatchActions(logic, [logic.actionCreators.setFilters({ insight: 'TRENDS', interval: 'minute' })])
                .toNotHaveDispatchedActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: partial({ interval: 'minute' }) })

            logic.actions.setFilters({ insight: 'TRENDS', interval: 'month' })
            await expectLogic()
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, {
                    searchParams: partial({ insight: 'TRENDS', interval: 'month' }),
                })
        })

        it('persists edit mode in the url', async () => {
            const url1 = combineUrl('/insights', cleanFilters({ insight: 'TRENDS' }), { fromItem: 42 })
            router.actions.push(url1.url)
            await expectLogic(logic)
                .toNotHaveDispatchedActions(['setInsightMode'])
                .toDispatchActions(['loadInsightSuccess'])
                .toMatchValues({
                    filters: partial({ insight: 'TRENDS' }),
                    insight: partial({ id: 42, result: ['result from api'] }),
                    insightMode: ItemMode.View,
                })

            const url2 = combineUrl('/insights', router.values.searchParams, { fromItem: 42, edit: true })
            router.actions.push(url2.url)
            await expectLogic(logic)
                .toDispatchActions([logic.actionCreators.setInsightMode(ItemMode.Edit, null)])
                .toMatchValues({
                    insightMode: ItemMode.Edit,
                })

            logic.actions.setInsightMode(ItemMode.View, null)
            expectLogic(router).toMatchValues({
                location: partial({ pathname: url1.pathname, search: url1.search, hash: url1.hash }),
            })

            logic.actions.setInsightMode(ItemMode.Edit, null)
            expectLogic(router).toMatchValues({
                location: partial({ pathname: url2.pathname, search: url2.search, hash: url2.hash }),
            })
        })
    })

    describe('takes data from other logics if available', () => {
        it('dashboardLogic', async () => {
            // 0. the feature flag must be set
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TURBO_MODE], { [FEATURE_FLAGS.TURBO_MODE]: true })

            // 1. the URL must have the dashboard and insight IDs
            router.actions.push('/insights', {}, { fromDashboard: 33, fromItem: 42 })

            // 2. the dashboard is mounted
            const dashLogic = dashboardLogic({ id: 33 })
            dashLogic.mount()
            await expectLogic(dashLogic).toDispatchActions(['loadDashboardItemsSuccess'])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: 42 })
            logic.mount()

            // 4. verify it didn't make any API calls
            await expectLogic(logic)
                .toDispatchActions(['setInsight'])
                .toNotHaveDispatchedActions(['setFilters', 'loadResults', 'loadInsight', 'updateInsight'])
                .toMatchValues({
                    insight: partial({ id: 42, result: 'result!', filters: { insight: 'TRENDS', interval: 'month' } }),
                })
        })

        it('savedInsightLogic', async () => {
            // 0. the feature flag must be set
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TURBO_MODE], { [FEATURE_FLAGS.TURBO_MODE]: true })

            // 1. open saved insights
            router.actions.push('/saved_insights', {}, {})
            savedInsightsLogic.mount()

            // 2. the insights are loaded
            await expectLogic(savedInsightsLogic).toDispatchActions(['loadInsights', 'loadInsightsSuccess'])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: 42 })
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
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SAVED_INSIGHTS], {
            [FEATURE_FLAGS.SAVED_INSIGHTS]: true,
        })

        logic = insightLogic({
            dashboardItemId: 42,
            filters: { insight: 'FUNNELS' },
        })
        logic.mount()

        // `setFilters` only changes `filters`, does not change `savedFilters`
        await expectLogic(logic, () => {
            logic.actions.setFilters({ insight: 'TRENDS' })
        }).toMatchValues({
            filters: partial({ insight: 'TRENDS' }),
            savedFilters: partial({ insight: 'FUNNELS' }),
            filtersChanged: true,
        })

        // results from search don't change anything
        await expectLogic(logic, () => {
            logic.actions.loadResultsSuccess({ id: 42, filters: { insight: 'PATHS' } })
        }).toMatchValues({
            filters: partial({ insight: 'TRENDS' }),
            savedFilters: partial({ insight: 'FUNNELS' }),
            filtersChanged: true,
        })

        // results from API GET and POST calls change saved filters
        await expectLogic(logic, () => {
            logic.actions.loadInsightSuccess({ id: 42, filters: { insight: 'PATHS' } })
        }).toMatchValues({
            filters: partial({ insight: 'TRENDS' }),
            savedFilters: partial({ insight: 'PATHS' }),
            filtersChanged: true,
        })
        await expectLogic(logic, () => {
            logic.actions.updateInsightSuccess({ id: 42, filters: { insight: 'RETENTION' } })
        }).toMatchValues({
            filters: partial({ insight: 'TRENDS' }),
            savedFilters: partial({ insight: 'RETENTION' }),
            filtersChanged: true,
        })

        // saving persists the in-flight filters
        await expectLogic(logic, () => {
            logic.actions.setFilters(API_FILTERS)
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            filters: partial({ insight: 'TRENDS' }),
            loadedFilters: partial({ insight: 'TRENDS' }),
            savedFilters: partial({ insight: 'RETENTION' }),
            filtersChanged: true,
        })

        await expectLogic(logic, () => {
            logic.actions.saveInsight()
        }).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            filters: partial({ insight: 'TRENDS' }),
            loadedFilters: partial({ insight: 'TRENDS' }),
            savedFilters: partial({ insight: 'TRENDS' }),
            filtersChanged: false,
        })
    })
})

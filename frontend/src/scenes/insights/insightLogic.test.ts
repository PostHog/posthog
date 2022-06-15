import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { createEmptyInsight, insightLogic } from './insightLogic'
import {
    AnyPropertyFilter,
    AvailableFeature,
    FilterLogicalOperator,
    InsightModel,
    InsightShortId,
    InsightType,
    ItemMode,
    PropertyGroupFilter,
    PropertyOperator,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { combineUrl, router } from 'kea-router'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'
import * as Sentry from '@sentry/react'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { useAvailableFeatures } from '~/mocks/features'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

const API_FILTERS = {
    insight: InsightType.TRENDS as InsightType,
    events: [{ id: 3 }],
    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
}

const Insight12 = '12' as InsightShortId
const Insight42 = '42' as InsightShortId
const Insight43 = '43' as InsightShortId
const Insight500 = '500' as InsightShortId

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.DASHBOARD_COLLABORATION])
        useMocks({
            get: {
                '/api/projects/:team/insights/trend/': (req) => {
                    if (JSON.parse(req.url.searchParams.get('events') || '[]')?.[0]?.throw) {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    return [200, { result: ['result from api'] }]
                },
                '/api/projects/:team/insights/path/': { result: ['result from api'] },
                '/api/projects/:team/insights/path': { result: ['result from api'] },
                '/api/projects/:team/insights/funnel/': { result: ['result from api'] },
                '/api/projects/:team/insights/retention/': { result: ['result from api'] },
                '/api/projects/:team/insights/': (req) => {
                    if (req.url.searchParams.get('saved')) {
                        return [
                            200,
                            {
                                results: [
                                    { id: 42, short_id: Insight42, result: ['result 42'], filters: API_FILTERS },
                                    { id: 43, short_id: Insight43, result: ['result 43'], filters: API_FILTERS },
                                ],
                            },
                        ]
                    }
                    const shortId = req.url.searchParams.get('short_id') || ''
                    if (shortId === '500') {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    return [
                        200,
                        {
                            results: [
                                {
                                    result: parseInt(shortId) === 42 ? ['result from api'] : null,
                                    id: parseInt(shortId),
                                    short_id: shortId.toString(),
                                    filters: JSON.parse(req.url.searchParams.get('filters') || 'false') || API_FILTERS,
                                },
                            ],
                        },
                    ]
                },
                '/api/projects/:team/dashboards/33/': {
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
                },
            },
            post: {
                '/api/projects/:team/insights/funnel/': { result: ['result from api'] },
                '/api/projects/:team/insights/:id/viewed': [201],
                '/api/projects/:team/insights/': (req) => [
                    200,
                    { id: 12, short_id: Insight12, ...((req.body as any) || {}) },
                ],
            },
            patch: {
                '/api/projects/:team/insights/:id': (req) => {
                    return [
                        200,
                        {
                            result: req.params['id'] === '42' ? ['result from api'] : null,
                            id: req.params['id'] === '42' ? 42 : 43,
                            short_id: req.params['id'] === '42' ? Insight42 : Insight43,
                            filters: JSON.parse(req.url.searchParams.get('filters') || 'false') || API_FILTERS,
                            name: req.params['id'] === '42' ? undefined : 'Foobar 43',
                            description: req.params['id'] === '42' ? undefined : 'Lorem ipsum.',
                            tags: req.params['id'] === '42' ? undefined : ['good'],
                        },
                    ]
                },
            },
        })
        initKeaTests()
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

    describe('insight legend', () => {
        it('toggles insight legend', async () => {
            logic = insightLogic({
                dashboardItemId: undefined,
                filters: { show_legend: false },
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.toggleInsightLegend()
            })
                .toDispatchActions(['toggleInsightLegend', 'setFilters'])
                .toMatchValues({
                    filters: partial({ show_legend: true }),
                })
        })
        it('initialize insight with hidden keys', async () => {
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: {
                    filters: { insight: InsightType.FUNNELS, hidden_legend_keys: { 0: true, 10: true } },
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                filters: partial({ hidden_legend_keys: { 0: true, 10: true } }),
            })
        })
        it('setHiddenById', async () => {
            logic = insightLogic({
                dashboardItemId: undefined,
            })
            logic.mount()

            expectLogic(logic, () => {
                logic.actions.setHiddenById({ '0': true, '2': false })
                logic.actions.setHiddenById({ '8': true, '2': true })
            }).toMatchValues({ hiddenLegendKeys: { 0: true, 2: true, 8: true } })
        })
        it('toggleVisibility', async () => {
            logic = insightLogic({
                dashboardItemId: undefined,
            })
            logic.mount()

            expectLogic(logic, () => {
                logic.actions.toggleVisibility(1)
            }).toMatchValues({ hiddenLegendKeys: { 1: true } })

            expectLogic(logic, () => {
                logic.actions.toggleVisibility(1)
            }).toMatchValues({ hiddenLegendKeys: { 1: undefined } })
        })
    })

    describe('analytics', () => {
        it('reports insight changes on setFilter', async () => {
            const insight = {
                filters: { insight: InsightType.TRENDS },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: InsightType.FUNNELS })
            }).toDispatchActions([
                eventUsageLogic.actionCreators.reportInsightViewed(
                    insight,
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
                    cachedInsight: {
                        short_id: Insight42,
                        results: ['cached result'],
                        filters: {
                            insight: InsightType.TRENDS,
                            events: [{ id: 2 }],
                            properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                        },
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
                        insight: partial({ short_id: Insight42, results: ['cached result'] }),
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
                    cachedInsight: {
                        short_id: Insight42,
                        results: undefined,
                        filters: {
                            insight: InsightType.TRENDS,
                            events: [{ id: 3 }],
                            properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                        },
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
            beforeEach(silenceKeaLoadersErrors)
            afterEach(resumeKeaLoadersErrors)

            it('makes a query to load the results', async () => {
                const insight = {
                    short_id: Insight42,
                    results: undefined,
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                }
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedInsight: insight,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadResults', 'loadResultsFailure'])
                    .toMatchValues({
                        insight: insight,
                        filters: partial({
                            events: [partial({ id: 3 })],
                            properties: [partial({ value: 'a' })],
                        }),
                        maybeShowErrorMessage: true,
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })

        describe('props with filters, no cached results, respects doNotLoad', () => {
            it('does not make a query', async () => {
                const insight = {
                    short_id: Insight42,
                    results: undefined,
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                }
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedInsight: insight,
                    doNotLoad: true,
                })
                logic.mount()

                await expectLogic(logic)
                    .toMatchValues({
                        insight: insight,
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
                    cachedInsight: {
                        short_id: Insight42,
                        results: undefined,
                        filters: undefined,
                    },
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
                    cachedInsight: undefined,
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
            beforeEach(silenceKeaLoadersErrors)
            afterEach(resumeKeaLoadersErrors)

            it('makes a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight500, // 500 --> result: throws
                    cachedInsight: undefined,
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightFailure'])
                    .toMatchValues({
                        insight: partial({ short_id: '500', result: null, filters: {} }),
                        filters: {},
                        maybeShowErrorMessage: true,
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['loadResults', 'setFilters', 'updateInsight'])
            })
        })
    })

    describe('takes data from other logics if available', () => {
        const verifyItLoadsFromALogic = async (
            logicUnderTest: ReturnType<typeof insightLogic.build>,
            partialExpectedInsight: Partial<InsightModel>
        ): Promise<void> =>
            expectLogic(logicUnderTest)
                .toDispatchActions(['setInsight'])
                .toNotHaveDispatchedActions(['setFilters', 'loadResults', 'loadInsight', 'updateInsight'])
                .toMatchValues({
                    insight: partial(partialExpectedInsight),
                })

        const verifyItLoadsFromTheAPI = async (logicUnderTest: ReturnType<typeof insightLogic.build>): Promise<void> =>
            expectLogic(logicUnderTest)
                .toDispatchActions(['loadInsight'])
                .toMatchValues({
                    insight: partial({
                        short_id: '42',
                    }),
                })

        it('loads from the dashboardLogic when in dashboard context', async () => {
            // 1. the dashboard is mounted
            const dashLogic = dashboardLogic({ id: 33 })
            dashLogic.mount()
            await expectLogic(dashLogic).toDispatchActions(['loadDashboardItemsSuccess'])

            // 2. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42, dashboardId: 33 })
            logic.mount()

            // 3. verify it didn't make any API calls
            await verifyItLoadsFromALogic(logic, {
                id: 42,
                result: 'result!',
                filters: { insight: InsightType.TRENDS, interval: 'month' },
            })
        })

        it('does not load from the dashboardLogic when not in that dashboard context', async () => {
            // 1. the dashboard is mounted
            const dashLogic = dashboardLogic({ id: 33 })
            dashLogic.mount()
            await expectLogic(dashLogic).toDispatchActions(['loadDashboardItemsSuccess'])

            // 2. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42, dashboardId: 1 })
            logic.mount()

            await verifyItLoadsFromTheAPI(logic)
        })

        it('loads from the savedInsightLogic when not in a dashboard context', async () => {
            // 1. open saved insights
            router.actions.push(urls.savedInsights(), {}, {})
            savedInsightsLogic.mount()

            // 2. the insights are loaded
            await expectLogic(savedInsightsLogic).toDispatchActions(['loadInsights', 'loadInsightsSuccess'])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42 })
            logic.mount()

            await verifyItLoadsFromALogic(logic, {
                short_id: '42' as InsightShortId,
            })
        })

        it('does not load from the savedInsightLogic when in a dashboard context', async () => {
            // 1. open saved insights
            router.actions.push(urls.savedInsights(), {}, {})
            savedInsightsLogic.mount()

            // 2. the insights are loaded
            await expectLogic(savedInsightsLogic).toDispatchActions(['loadInsights', 'loadInsightsSuccess'])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42, dashboardId: 33 })
            logic.mount()

            await verifyItLoadsFromTheAPI(logic)
        })
    })

    test('keeps saved filters', async () => {
        logic = insightLogic({
            dashboardItemId: Insight42,
            cachedInsight: { filters: { insight: InsightType.FUNNELS } },
        })
        logic.mount()

        // `setFilters` only changes `filters`, does not change `savedInsight`
        await expectLogic(logic, () => {
            logic.actions.setFilters({ insight: InsightType.TRENDS })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedInsight: partial({ filters: { insight: InsightType.FUNNELS } }),
            insightChanged: true,
        })

        // results from search don't change anything
        await expectLogic(logic, () => {
            logic.actions.loadResultsSuccess({
                short_id: Insight42,
                filters: { insight: InsightType.PATHS },
            })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedInsight: partial({ filters: { insight: InsightType.FUNNELS } }),
            insightChanged: true,
        })

        // results from API GET and POST calls change saved filters
        await expectLogic(logic, () => {
            logic.actions.loadInsightSuccess({
                short_id: Insight42,
                filters: { insight: InsightType.PATHS },
            })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedInsight: partial({ filters: partial({ insight: InsightType.PATHS }) }),
            insightChanged: true,
        })
        await expectLogic(logic, () => {
            logic.actions.updateInsightSuccess({
                short_id: Insight42,
                filters: { insight: InsightType.RETENTION },
            })
        }).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            savedInsight: partial({ filters: partial({ insight: InsightType.RETENTION }) }),
            insightChanged: true,
        })

        // saving persists the in-flight filters
        await expectLogic(logic, () => {
            logic.actions.setFilters(API_FILTERS)
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            loadedFilters: partial({ insight: InsightType.TRENDS }),
            savedInsight: partial({ filters: partial({ insight: InsightType.RETENTION }) }),
            insightChanged: true,
        })

        await expectLogic(logic, () => {
            logic.actions.saveInsight()
        }).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            filters: partial({ insight: InsightType.TRENDS }),
            loadedFilters: partial({ insight: InsightType.TRENDS }),
            savedInsight: partial({ filters: partial({ insight: InsightType.TRENDS }) }),
            insightChanged: false,
        })
    })

    test('keeps saved name, description, tags', async () => {
        logic = insightLogic({
            dashboardItemId: Insight43,
            cachedInsight: { ...createEmptyInsight(Insight43), filters: API_FILTERS },
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            insight: partial({ name: '', description: '', tags: [] }),
            savedInsight: partial({ name: '', description: '', tags: [] }),
            insightChanged: false,
        })

        await expectLogic(logic, () => {
            logic.actions.setInsightMetadata({ name: 'Foobar 43', description: 'Lorem ipsum.', tags: ['good'] })
        }).toMatchValues({
            insight: partial({ name: 'Foobar 43', description: 'Lorem ipsum.', tags: ['good'] }),
            savedInsight: partial({ name: '', description: '', tags: [] }),
            insightChanged: true,
        })

        await expectLogic(logic, () => {
            logic.actions.saveInsight()
        }).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            insight: partial({ name: 'Foobar 43', description: 'Lorem ipsum.', tags: ['good'] }),
            savedInsight: partial({ name: 'Foobar 43', description: 'Lorem ipsum.', tags: ['good'] }),
            insightChanged: false,
        })
    })

    test('saveInsight saves new insight and redirects to view mode', async () => {
        logic = insightLogic({
            dashboardItemId: 'new',
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setFilters(cleanFilters({}))
            logic.actions.saveInsight()
        }).toDispatchActions(['setFilters', 'saveInsight', router.actionCreators.push(urls.insightView(Insight12))])
    })

    test('saveInsight and updateInsight reload the saved insights list', async () => {
        savedInsightsLogic.mount()
        logic = insightLogic({
            dashboardItemId: Insight42,
            cachedInsight: {
                short_id: Insight42,
                filters: { insight: InsightType.FUNNELS },
                results: {},
            },
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
            cachedInsight: {
                filters: { insight: InsightType.FUNNELS },
            },
        })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.saveAsNamingSuccess('New Insight (copy)')
        })
            .toDispatchActions(['setInsight'])
            .toDispatchActions(savedInsightsLogic, ['loadInsights'])
            .toMatchValues({
                savedInsight: partial({ filters: partial({ insight: InsightType.FUNNELS }) }),
                filters: partial({ insight: InsightType.FUNNELS }),
                insight: partial({ id: 12, short_id: Insight12, name: 'New Insight (copy)' }),
                insightChanged: false,
            })

        await expectLogic(router)
            .toDispatchActions(['push', 'locationChanged'])
            .toMatchValues({
                location: partial({ pathname: '/insights/12/edit' }),
            })
    })

    test('will not save with empty filters', async () => {
        jest.spyOn(Sentry, 'captureException')
        logic = insightLogic({
            dashboardItemId: Insight42,
            filters: { insight: InsightType.FUNNELS },
        })
        logic.mount()

        logic.actions.setInsight({ id: 42, short_id: Insight42, filters: {} }, {})
        logic.actions.saveInsight()
        expect(Sentry.captureException).toHaveBeenCalledWith(
            new Error('Will not override empty filters in saveInsight.'),
            expect.any(Object)
        )
    })

    describe('filterPropertiesCount selector', () => {
        const standardPropertyFilter = { value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }
        const cases: {
            properties: AnyPropertyFilter[] | PropertyGroupFilter
            count: number
        }[] = [
            {
                properties: [standardPropertyFilter],
                count: 1,
            },
            {
                properties: [standardPropertyFilter, standardPropertyFilter],
                count: 2,
            },
            {
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.Or,
                            values: [standardPropertyFilter, standardPropertyFilter],
                        },
                        {
                            type: FilterLogicalOperator.And,
                            values: [standardPropertyFilter, standardPropertyFilter, standardPropertyFilter],
                        },
                    ],
                },
                count: 5,
            },
        ]

        it.each(cases)('returns the correct count for filter properties', ({ properties, count }) => {
            logic = insightLogic({
                dashboardItemId: Insight42,
                cachedInsight: {
                    short_id: Insight42,
                    results: ['cached result'],
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 2 }],
                        properties,
                    },
                },
            })
            logic.mount()
            expectLogic(logic).toMatchValues({
                filterPropertiesCount: count,
            })
        })
    })

    describe('setFilters with new entity', () => {
        it('does not call the api on empty filters', async () => {
            const insight = {
                result: ['result from api'],
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ new_entity: [] })
            }).toNotHaveDispatchedActions(['loadResults'])
        })
    })
})

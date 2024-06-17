import { combineUrl, router } from 'kea-router'
import { expectLogic, partial, truth } from 'kea-test-utils'
import api from 'lib/api'
import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'
import { DashboardPrivilegeLevel, DashboardRestrictionLevel } from 'lib/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { initKeaTests } from '~/test/init'
import {
    AnyPropertyFilter,
    BreakdownType,
    DashboardTile,
    DashboardType,
    FilterLogicalOperator,
    FilterType,
    FunnelsFilterType,
    InsightModel,
    InsightShortId,
    InsightType,
    ItemMode,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { createEmptyInsight, insightLogic } from './insightLogic'

const API_FILTERS: Partial<FilterType> = {
    insight: InsightType.TRENDS as InsightType,
    events: [{ id: 3 }],
    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' } as any as AnyPropertyFilter],
}

const Insight12 = '12' as InsightShortId
const Insight42 = '42' as InsightShortId
const Insight43 = '43' as InsightShortId
const Insight44 = '44' as InsightShortId

const partialInsight43 = {
    id: 43,
    short_id: Insight43,
    result: ['result 43'],
    filters: API_FILTERS,
}

const patchResponseFor = (
    payload: Record<string, any>,
    id: string,
    filters: Record<string, any>
): Record<string, any> => {
    return {
        result: id === '42' ? ['result from api'] : null,
        id: id === '42' ? 42 : 43,
        short_id: id === '42' ? Insight42 : Insight43,
        filters: filters || API_FILTERS,
        name: id === '42' ? undefined : 'Foobar 43',
        description: id === '42' ? undefined : 'Lorem ipsum.',
        tags: id === '42' ? undefined : ['good'],
        dashboards: payload['dashboards'],
    }
}

function insightModelWith(properties: Record<string, any>): InsightModel {
    return {
        id: 42,
        short_id: Insight42,
        result: ['result 42'],
        filters: API_FILTERS,
        dashboards: [],
        dashboard_tiles: [],
        saved: true,
        name: 'new name',
        order: null,
        last_refresh: null,
        created_at: '2021-03-09T14: 00: 00.000Z',
        created_by: null,
        deleted: false,
        description: '',
        is_sample: false,
        is_shared: null,
        pinned: null,
        refresh_interval: null,
        updated_at: '2021-03-09T14: 00: 00.000Z',
        updated_by: null,
        visibility: null,
        last_modified_at: '2021-03-31T15:00:00.000Z',
        last_modified_by: null,
        effective_privilege_level: DashboardPrivilegeLevel.CanEdit,
        effective_restriction_level: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
        layouts: {},
        color: null,
        ...properties,
    } as InsightModel
}

const seenQueryIDs: string[] = []

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/tags': [],
                '/api/projects/:team/insights/trend/': async (req) => {
                    const clientQueryId = req.url.searchParams.get('client_query_id')
                    if (clientQueryId !== null) {
                        seenQueryIDs.push(clientQueryId)
                    }

                    if (JSON.parse(req.url.searchParams.get('events') || '[]')?.[0]?.throw) {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    if (req.url.searchParams.get('date_from') === '-180d') {
                        // delay for 2 seconds before response without pausing
                        return new Promise((resolve) =>
                            setTimeout(() => {
                                resolve([200, { result: ['very slow result from api'] }])
                            }, 2000)
                        )
                    }
                    return [200, { result: ['result from api'] }]
                },
                '/api/projects/:team/insights/path/': { result: ['result from api'] },
                '/api/projects/:team/insights/path': { result: ['result from api'] },
                '/api/projects/:team/insights/funnel/': { result: ['result from api'] },
                '/api/projects/:team/insights/retention/': { result: ['result from api'] },
                '/api/projects/:team/insights/43/': partialInsight43,
                '/api/projects/:team/insights/44/': {
                    id: 44,
                    short_id: Insight44,
                    result: ['result 44'],
                    filters: API_FILTERS,
                },
                '/api/projects/:team/insights/': (req) => {
                    if (req.url.searchParams.get('saved')) {
                        return [
                            200,
                            {
                                results: [
                                    {
                                        id: 42,
                                        short_id: Insight42,
                                        result: ['result 42'],
                                        filters: API_FILTERS,
                                        name: 'original name',
                                        dashboards: [1, 2, 3],
                                    },
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
                                    name: 'original name',
                                    dashboards: [1, 2, 3],
                                },
                            ],
                        },
                    ]
                },
                '/api/projects/:team/dashboards/33/': {
                    id: 33,
                    filters: {},
                    tiles: [
                        {
                            layouts: {},
                            color: null,
                            insight: {
                                id: 42,
                                short_id: Insight42,
                                result: 'result!',
                                filters: { insight: InsightType.TRENDS, interval: 'month' },
                                tags: ['bla'],
                            },
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
                '/api/projects/997/insights/cancel/': [201],
            },
            patch: {
                '/api/projects/:team/insights/:id': async (req) => {
                    const payload = await req.json()
                    const response = patchResponseFor(
                        payload,
                        req.params['id'] as string,
                        JSON.parse(req.url.searchParams.get('filters') || 'false')
                    )
                    return [200, response]
                },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
        teamLogic.mount()
        await expectLogic(teamLogic)
            .toFinishAllListeners()
            .toMatchValues({ currentTeam: partial({ test_account_filters_default_checked: true }) })
        insightsModel.mount()
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
                    },
                    false
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
                            properties: [
                                {
                                    value: 'lol',
                                    operator: PropertyOperator.Exact,
                                    key: 'lol',
                                    type: PropertyFilterType.Person,
                                },
                            ],
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
                            properties: [partial({ type: PropertyFilterType.Person })],
                        }),
                    })
                    .toNotHaveDispatchedActions(['loadResultsSuccess']) // this took the cached results
            })
        })

        describe('props with query and cached results', () => {
            beforeEach(() => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedInsight: {
                        short_id: Insight42,
                        results: ['cached result'],
                        filters: {},
                        query: { kind: NodeKind.TimeToSeeDataSessionsQuery },
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
                        insight: partial({
                            short_id: Insight42,
                            results: ['cached result'],
                            query: { kind: NodeKind.TimeToSeeDataSessionsQuery },
                        }),
                        filters: {},
                    })
                    .toNotHaveDispatchedActions(['loadResultsSuccess']) // this took the cached results
            })
        })

        describe('props with query, no cached results', () => {
            it('still does not make a query to load the results', async () => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedInsight: {
                        short_id: Insight42,
                        results: undefined,
                        filters: {},
                        query: { kind: NodeKind.TimeToSeeDataSessionsQuery },
                    },
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions([])
                    .toMatchValues({
                        insight: partial({ short_id: Insight42, query: { kind: NodeKind.TimeToSeeDataSessionsQuery } }),
                        filters: {},
                    })
                    .delay(1)
                    // do not override the insight if querying with different filters
                    .toNotHaveDispatchedActions([
                        'loadResults',
                        'loadResultsSuccess',
                        'updateInsight',
                        'updateInsightSuccess',
                    ])
            })
        })

        describe('props with filters, no cached results, respects doNotLoad', () => {
            it('does not make a query', async () => {
                const insight: Partial<InsightModel> = {
                    short_id: Insight42,
                    filters: {
                        insight: InsightType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [
                            { value: 'a', operator: PropertyOperator.Exact, key: 'a', type: PropertyFilterType.Person },
                        ],
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
    })

    describe('takes data from other logics if available', () => {
        const verifyItLoadsFromTheAPI = async (logicUnderTest: ReturnType<typeof insightLogic.build>): Promise<void> =>
            expectLogic(logicUnderTest)
                .toDispatchActions(['loadInsight'])
                .toMatchValues({
                    insight: partial({
                        short_id: '42',
                    }),
                })

        it('loads from the api when coming from dashboard context', async () => {
            // 1. the dashboard is mounted
            const dashLogic = dashboardLogic({ id: 33 })
            dashLogic.mount()
            await expectLogic(dashLogic).toDispatchActions(['loadDashboardSuccess'])

            // 2. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42, dashboardId: 33 })
            logic.mount()

            await verifyItLoadsFromTheAPI(logic)
        })

        it('does not load from the dashboardLogic when not in that dashboard context', async () => {
            // 1. the dashboard is mounted
            const dashLogic = dashboardLogic({ id: 33 })
            dashLogic.mount()
            await expectLogic(dashLogic).toDispatchActions(['loadDashboardSuccess'])

            // 2. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42, dashboardId: 1 })
            logic.mount()

            await verifyItLoadsFromTheAPI(logic)
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

    test('can default filter test accounts to on', async () => {
        logic = insightLogic({
            dashboardItemId: 'new',
        })
        logic.mount()

        const expectedPartialInsight = {
            description: '',
            filters: { filter_test_accounts: true },
            name: '',
            result: null,
            short_id: undefined,
            tags: [],
        }

        await expectLogic(logic).toMatchValues({
            insight: partial(expectedPartialInsight),
            savedInsight: {},
            insightChanged: false,
        })
    })

    test('keeps saved name, description, tags', async () => {
        logic = insightLogic({
            dashboardItemId: Insight43,
            cachedInsight: { ...createEmptyInsight(Insight43, false), filters: API_FILTERS },
        })
        logic.mount()

        const expectedPartialInsight = {
            name: '',
            description: '',
            tags: [],
            filters: {
                events: [{ id: 3 }],
                insight: 'TRENDS',
                properties: [{ key: 'a', operator: 'exact', type: 'a', value: 'a' }],
            },
        }
        await expectLogic(logic).toMatchValues({
            insight: partial(expectedPartialInsight),
            savedInsight: partial(expectedPartialInsight),
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

    test('saveInsight and updateInsight update the saved insights list', async () => {
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
        await expectLogic(logic).toDispatchActions([savedInsightsLogic.actionTypes.addInsight])

        logic.actions.updateInsight({ filters: { insight: InsightType.FUNNELS } })
        await expectLogic(logic).toDispatchActions([savedInsightsLogic.actionTypes.setInsight])
    })

    test('saveInsight updates dashboards', async () => {
        savedInsightsLogic.mount()
        logic = insightLogic({
            dashboardItemId: Insight43,
        })
        logic.mount()

        logic.actions.saveInsight()
        await expectLogic(dashboardsModel).toDispatchActions(['updateDashboardInsight'])
    })

    test('updateInsight updates dashboards', async () => {
        savedInsightsLogic.mount()
        logic = insightLogic({
            dashboardItemId: Insight43,
        })
        logic.mount()

        logic.actions.updateInsight({ name: 'updated name' })
        await expectLogic(dashboardsModel).toDispatchActions(['updateDashboardInsight'])
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

    describe('hiddenLegendKeys selector', () => {
        it('properly migrates pre-#12113 visibility keys', async () => {
            logic = insightLogic({
                dashboardItemId: Insight42,
                cachedInsight: {
                    short_id: Insight42,
                    results: undefined,
                    filters: {
                        insight: InsightType.FUNNELS,
                        hidden_legend_keys: {
                            // Pre-#12113 funnel visibility key style
                            'events/$pageview/0/Baseline': true,
                            'events/$pageview/1/Baseline': undefined,
                            // Post-#12113 funnel visibility key style
                            'Chrome OS': undefined,
                            Windows: true,
                        },
                    },
                },
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                hiddenLegendKeys: {
                    // 'events/$pageview/0/Baseline' should be transformed to 'Baseline'
                    Baseline: true,
                    'Chrome OS': undefined,
                    Windows: true,
                },
            })
        })
    })

    describe('emptyFilters', () => {
        let theEmptyFiltersLogic: ReturnType<typeof insightLogic.build>
        beforeEach(() => {
            const insight = {
                result: ['result from api'],
            }
            theEmptyFiltersLogic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            theEmptyFiltersLogic.mount()
        })

        it('does not call the api on setting empty filters', async () => {
            await expectLogic(theEmptyFiltersLogic, () => {
                theEmptyFiltersLogic.actions.setFilters({ new_entity: [] } as FunnelsFilterType)
            }).toNotHaveDispatchedActions(['loadResults'])
        })

        it('does not call the api on update when empty filters and no query', async () => {
            await expectLogic(theEmptyFiltersLogic, () => {
                theEmptyFiltersLogic.actions.updateInsight({
                    name: 'name',
                    filters: {},
                    query: undefined,
                })
            }).toNotHaveDispatchedActions(['updateInsightSuccess'])
        })

        it('does call the api on update when empty filters but query is present', async () => {
            await expectLogic(theEmptyFiltersLogic, () => {
                theEmptyFiltersLogic.actions.updateInsight({
                    name: 'name',
                    filters: {},
                    query: { kind: NodeKind.DataTableNode } as DataTableNode,
                })
            }).toDispatchActions(['updateInsightSuccess'])
        })
    })

    describe('isUsingSessionAnalysis selector', () => {
        it('is false by default', async () => {
            const insight = {
                filters: { insight: InsightType.TRENDS },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()
            expectLogic(logic).toMatchValues({ isUsingSessionAnalysis: false })
        })

        it('setting session breakdown sets it true', async () => {
            const insight = {
                filters: { insight: InsightType.TRENDS, breakdown_type: 'session' as BreakdownType },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()
            expectLogic(logic).toMatchValues({ isUsingSessionAnalysis: true })
        })

        it('setting global session property filters sets it true', async () => {
            const insight: Partial<InsightModel> = {
                filters: {
                    insight: InsightType.TRENDS,
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        key: '$session_duration',
                                        value: 1,
                                        operator: PropertyOperator.GreaterThan,
                                        type: PropertyFilterType.Session,
                                    },
                                ],
                            },
                        ],
                    },
                },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()
            expectLogic(logic).toMatchValues({ isUsingSessionAnalysis: true })
        })

        it('setting entity session property filters sets it true', async () => {
            const insight = {
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                            properties: [
                                {
                                    key: '$session_duration',
                                    value: 1,
                                    operator: PropertyOperator.GreaterThan,
                                    type: 'session',
                                },
                            ],
                        },
                    ],
                },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()
            expectLogic(logic).toMatchValues({ isUsingSessionAnalysis: true })
        })

        it('setting math to unique_session sets it true', async () => {
            const insight = {
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                            properties: [],
                            math: 'unique_session',
                        },
                    ],
                },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()
            expectLogic(logic).toMatchValues({ isUsingSessionAnalysis: true })
        })

        it('setting math to use session property sets it true', async () => {
            const insight = {
                filters: {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                            properties: [],
                            math: 'median',
                            math_property: '$session_duration',
                        },
                    ],
                },
            }
            logic = insightLogic({
                dashboardItemId: undefined,
                cachedInsight: insight,
            })
            logic.mount()
            expectLogic(logic).toMatchValues({ isUsingSessionAnalysis: true })
        })
    })

    describe('reacts to external changes', () => {
        beforeEach(async () => {
            logic = insightLogic({
                dashboardItemId: Insight42,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadInsight']).toFinishAllListeners()
        })

        it('reacts to rename of its own insight', async () => {
            await expectLogic(logic, () => {
                insightsModel.actions.renameInsightSuccess(
                    insightModelWith({
                        id: 42,
                        short_id: Insight42,
                        result: ['result 42'],
                        filters: API_FILTERS,
                        name: 'new name',
                    })
                )
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: truth(({ name }) => {
                        return name === 'new name'
                    }),
                })
        })

        it('does not react to rename of a different insight', async () => {
            await expectLogic(logic, () => {
                insightsModel.actions.renameInsightSuccess(
                    insightModelWith({
                        id: 43,
                        short_id: Insight43,
                        result: ['result 43'],
                        filters: API_FILTERS,
                        name: 'not the insight for this logic',
                    })
                )
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: truth(({ name }) => {
                        return name === 'original name'
                    }),
                })
        })

        it('reacts to removal from dashboard', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.tileRemovedFromDashboard({
                    tile: { insight: { id: 42 } } as DashboardTile,
                    dashboardId: 3,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2] }),
                })
        })

        it('does not reacts to removal of a different tile from dashboard', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.tileRemovedFromDashboard({
                    tile: { insight: { id: 12 } } as DashboardTile,
                    dashboardId: 3,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2, 3] }),
                })
        })

        it('reacts to deletion of dashboard', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.deleteDashboardSuccess({ id: 3 } as DashboardType)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2] }),
                })
        })

        it('does not reacts to deletion of dashboard it is not on', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.deleteDashboardSuccess({ id: 1034 } as DashboardType)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2, 3] }),
                })
        })

        it('reacts to duplication of dashboard attaching it to new dashboard', async () => {
            await expectLogic(logic, () => {
                insightsModel.actions.insightsAddedToDashboard({ dashboardId: 1234, insightIds: [0, 1, 42] })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2, 3, 1234] }),
                })
        })

        it('does not react to duplication of dashboard that did not include this insight', async () => {
            await expectLogic(logic, () => {
                insightsModel.actions.insightsAddedToDashboard({ dashboardId: 1234, insightIds: [0, 1, 2] })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2, 3] }),
                })
        })
    })

    describe('saving query based insights', () => {
        beforeEach(async () => {
            logic = insightLogic({
                dashboardItemId: 'new',
            })
            logic.mount()
        })

        it('sends query when saving', async () => {
            jest.spyOn(api, 'create')

            await expectLogic(logic, () => {
                logic.actions.setInsight(
                    { filters: {}, query: { kind: NodeKind.DataTableNode } as DataTableNode },
                    { overrideFilter: true }
                )
                logic.actions.saveInsight()
            })

            const mockCreateCalls = (api.create as jest.Mock).mock.calls
            expect(mockCreateCalls).toEqual([
                [
                    `api/projects/${MOCK_TEAM_ID}/insights/`,
                    {
                        derived_name: 'DataTableNode query',
                        filters: {},
                        query: {
                            kind: 'DataTableNode',
                        },
                        saved: true,
                    },
                ],
            ])
        })
    })
})

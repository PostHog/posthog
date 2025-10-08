import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, partial, truth } from 'kea-test-utils'

import api from 'lib/api'
import 'lib/constants'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { examples } from '~/queries/examples'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AnyPropertyFilter,
    DashboardTile,
    DashboardType,
    FilterType,
    InsightLogicProps,
    InsightShortId,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
} from '~/types'

import { insightDataLogic } from './insightDataLogic'
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

const MOCK_DASHBOARD_ID = 34

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
        dashboard_tiles: id === '43' ? [{ dashboard_id: MOCK_DASHBOARD_ID }] : undefined,
    }
}

function insightModelWith(properties: Record<string, any>): QueryBasedInsightModel {
    return {
        id: 42,
        short_id: Insight42,
        result: ['result 42'],
        query: queryFromFilters(API_FILTERS),
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
        layouts: {},
        color: null,
        user_access_level: AccessControlLevel.Editor,
        ...properties,
    } as QueryBasedInsightModel
}

const seenQueryIDs: string[] = []

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/tags': [],
                '/api/environments/:team_id/insights/trend/': async (req) => {
                    const clientQueryId = req.url.searchParams.get('client_query_id')
                    if (clientQueryId !== null) {
                        seenQueryIDs.push(clientQueryId)
                    }

                    if (JSON.parse(req.url.searchParams.get('events') || '[]')?.[0]?.throw) {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    if (req.url.searchParams.get('date_from') === '-180d') {
                        // delay for 2 seconds before response without pausing
                        return new Promise<[number, { result: string[] }]>((resolve) =>
                            setTimeout(() => {
                                resolve([200, { result: ['very slow result from api'] }])
                            }, 2000)
                        )
                    }
                    return [200, { result: ['result from api'] }]
                },
                '/api/environments/:team_id/insights/path/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/path': { result: ['result from api'] },
                '/api/environments/:team_id/insights/funnel/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/retention/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/43/': partialInsight43,
                '/api/environments/:team_id/insights/44/': {
                    id: 44,
                    short_id: Insight44,
                    result: ['result 44'],
                    filters: API_FILTERS,
                },
                '/api/environments/:team_id/insights/': (req) => {
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
                '/api/environments/:team_id/dashboards/33/': {
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
                '/api/environments/:team_id/dashboards/34/': {
                    id: 33,
                    filters: {},
                    tiles: [
                        {
                            layouts: {},
                            color: null,
                            insight: {
                                id: 42,
                                short_id: Insight43,
                                result: 'result!',
                                filters: { insight: InsightType.TRENDS, interval: 'month' },
                                tags: ['bla'],
                            },
                        },
                    ],
                },
            },
            post: {
                '/api/environments/:team_id/insights/funnel/': { result: ['result from api'] },
                '/api/environments/:team_id/insights/viewed': [201],
                '/api/environments/:team_id/insights/': (req) => [
                    200,
                    { id: 12, short_id: Insight12, ...(req.body as any) },
                ],
                '/api/environments/997/insights/cancel/': [201],
            },
            patch: {
                '/api/environments/:team_id/insights/:id': async (req) => {
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
        sceneLogic.mount()
        sceneLogic.actions.setTabs([
            { id: '1', title: '...', pathname: '/', search: '', hash: '', active: true, iconType: 'blank' },
        ])
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
        })

        describe('props with query and cached results', () => {
            beforeEach(() => {
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedInsight: {
                        short_id: Insight42,
                        results: ['cached result'],
                        filters: {},
                        query: { kind: NodeKind.EventsQuery },
                    },
                })
                logic.mount()
            })

            it('has the key set to the id', () => {
                expect(logic.key).toEqual('42')
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
                        query: { kind: NodeKind.EventsQuery },
                    },
                })
                logic.mount()

                await expectLogic(logic)
                    .toDispatchActions([])
                    .toMatchValues({
                        insight: partial({
                            short_id: Insight42,
                            query: { kind: NodeKind.EventsQuery },
                        }),
                    })
                    .delay(1)
                    // do not override the insight if querying with different filters
                    .toNotHaveDispatchedActions(['updateInsight', 'updateInsightSuccess'])
            })
        })

        describe('props with filters, no cached results, respects doNotLoad', () => {
            it('does not make a query', async () => {
                const insight: Partial<QueryBasedInsightModel> = {
                    short_id: Insight42,
                    query: queryFromFilters({
                        insight: InsightType.TRENDS,
                        events: [{ id: 3, throw: true }],
                        properties: [
                            { value: 'a', operator: PropertyOperator.Exact, key: 'a', type: PropertyFilterType.Person },
                        ],
                    }),
                }
                logic = insightLogic({
                    dashboardItemId: Insight42,
                    cachedInsight: insight,
                    doNotLoad: true,
                })
                logic.mount()

                await expectLogic(logic)
                    .toMatchValues({
                        insight: {
                            short_id: Insight42,
                            query: {
                                kind: 'InsightVizNode',
                                source: {
                                    kind: 'TrendsQuery',
                                    properties: {
                                        type: 'AND',
                                        values: [
                                            {
                                                type: 'AND',
                                                values: [partial({ value: 'a' })],
                                            },
                                        ],
                                    },
                                    series: [partial({ event: 3 })],
                                },
                            },
                        },
                    })
                    .delay(1)
                    .toNotHaveDispatchedActions(['setFilters', 'updateInsight'])
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
            savedInsightsLogic({ tabId: '1' }).mount()

            // 2. the insights are loaded
            await expectLogic(savedInsightsLogic({ tabId: '1' })).toDispatchActions([
                'loadInsights',
                'loadInsightsSuccess',
            ])

            // 3. mount the insight
            logic = insightLogic({ dashboardItemId: Insight42, dashboardId: 33 })
            logic.mount()

            await verifyItLoadsFromTheAPI(logic)
        })
    })

    test('keeps saved name, description, tags', async () => {
        const insightProps: InsightLogicProps = {
            dashboardItemId: Insight43,
            cachedInsight: { ...createEmptyInsight(Insight43), id: 123, query: queryFromFilters(API_FILTERS) },
        }

        logic = insightLogic(insightProps)
        logic.mount()

        insightDataLogic(insightProps).mount()

        const expectedPartialInsight = {
            name: '',
            description: '',
            tags: [],
            query: partial({
                source: partial({
                    series: [{ event: 3, kind: NodeKind.EventsNode, math: 'total' }],
                    kind: NodeKind.TrendsQuery,
                    properties: {
                        type: 'AND',
                        values: [{ type: 'AND', values: [{ key: 'a', operator: 'exact', type: 'a', value: 'a' }] }],
                    },
                }),
            }),
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
        const insightProps: InsightLogicProps = {
            dashboardItemId: 'new',
        }

        logic = insightLogic(insightProps)
        logic.mount()

        insightDataLogic(insightProps).mount()

        await expectLogic(logic, () => {
            logic.actions.saveInsight()
        }).toDispatchActions(['saveInsight', router.actionCreators.push(urls.insightView(Insight12))])
    })

    test('saveInsight and updateInsight update the saved insights list', async () => {
        savedInsightsLogic({ tabId: '1' }).mount()

        const insightProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            cachedInsight: {
                short_id: Insight42,
                query: examples.FunnelsQuery,
                result: {},
            },
        }

        logic = insightLogic(insightProps)
        logic.mount()

        insightDataLogic(insightProps).mount()

        logic.actions.saveInsight()
        await expectLogic(logic).toDispatchActions([savedInsightsLogic({ tabId: '1' }).actionTypes.addInsight])

        logic.actions.updateInsight({ name: 'my new name' })
        await expectLogic(logic).toDispatchActions([savedInsightsLogic({ tabId: '1' }).actionTypes.updateInsight])
    })

    test('saveInsight updates dashboards', async () => {
        const dashLogic = dashboardLogic({ id: MOCK_DASHBOARD_ID })
        dashLogic.mount()
        await expectLogic(dashLogic).toDispatchActions(['loadDashboard'])

        savedInsightsLogic({ tabId: '1' }).mount()

        const insightProps: InsightLogicProps = {
            dashboardItemId: Insight43,
        }
        logic = insightLogic(insightProps)
        logic.mount()

        insightDataLogic(insightProps).mount()

        logic.actions.saveInsight()

        await expectLogic(dashLogic).toDispatchActions(['loadDashboard'])
    })

    test('updateInsight updates dashboards', async () => {
        savedInsightsLogic({ tabId: '1' }).mount()
        logic = insightLogic({
            dashboardItemId: Insight43,
            cachedInsight: {
                id: 3,
            },
        })
        logic.mount()

        logic.actions.updateInsight({ name: 'updated name' })
        await expectLogic(dashboardsModel).toDispatchActions(['updateDashboardInsight'])
    })

    test('save as new insight', async () => {
        savedInsightsLogic({ tabId: '1' }).mount()

        const insightProps: InsightLogicProps = {
            dashboardItemId: Insight42,
            cachedInsight: {
                query: examples.InsightFunnels,
            },
        }

        logic = insightLogic(insightProps)
        logic.mount()

        insightDataLogic(insightProps).mount()

        await expectLogic(logic, () => {
            logic.actions.saveAsConfirmation('New Insight (copy)')
        })
            .toDispatchActions(['setInsight'])
            .toDispatchActions(savedInsightsLogic({ tabId: '1' }), ['loadInsights'])
            .toMatchValues({
                savedInsight: partial({ query: partial({ source: partial({ kind: NodeKind.FunnelsQuery }) }) }),
                insight: partial({
                    id: 12,
                    short_id: Insight12,
                    name: 'New Insight (copy)',
                    query: partial({ source: partial({ kind: NodeKind.FunnelsQuery }) }),
                }),
                insightChanged: false,
            })

        await expectLogic(router)
            .toDispatchActions(['push', 'locationChanged'])
            .toMatchValues({
                location: partial({ pathname: '/project/997/insights/12/edit' }),
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
                    tile: { insight: { id: 42 } } as DashboardTile<QueryBasedInsightModel>,
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
                    tile: { insight: { id: 12 } } as DashboardTile<QueryBasedInsightModel>,
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
                dashboardsModel.actions.deleteDashboardSuccess({ id: 3 } as DashboardType<QueryBasedInsightModel>)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    insight: expect.objectContaining({ dashboards: [1, 2] }),
                })
        })

        it('does not reacts to deletion of dashboard it is not on', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.deleteDashboardSuccess({ id: 1034 } as DashboardType<QueryBasedInsightModel>)
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
            const insightProps: InsightLogicProps = { dashboardItemId: 'new' }
            logic = insightLogic(insightProps)
            logic.mount()

            insightDataLogic(insightProps).mount()
        })

        it('sends query when saving', async () => {
            jest.spyOn(api, 'create')

            await expectLogic(logic, () => {
                logic.actions.setInsight(
                    { query: { kind: NodeKind.DataTableNode } as DataTableNode },
                    { overrideQuery: true }
                )
                logic.actions.saveInsight()
            })

            const mockCreateCalls = (api.create as jest.Mock).mock.calls
            expect(mockCreateCalls).toEqual([
                [
                    `api/environments/${MOCK_TEAM_ID}/insights`,
                    expect.objectContaining({
                        derived_name: 'DataTableNode query',
                        query: {
                            kind: 'DataTableNode',
                        },
                        saved: true,
                    }),
                    expect.objectContaining({
                        data: {
                            derived_name: 'DataTableNode query',
                            query: {
                                kind: 'DataTableNode',
                            },
                            saved: true,
                        },
                    }),
                ],
            ])
        })
    })
})

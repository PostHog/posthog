// let tiles assert an insight is present in tests i.e. `tile!.insight` when it must be present for tests to pass
import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic, truth } from 'kea-test-utils'

import api from 'lib/api'
import { now } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { examples } from '~/queries/examples'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { DashboardTile, DashboardType, InsightColor, InsightShortId, QueryBasedInsightModel } from '~/types'

import _dashboardJson from './__mocks__/dashboard.json'

const dashboardJson = getQueryBasedDashboard(_dashboardJson as any as DashboardType)!

export function insightOnDashboard(
    insightId: number,
    dashboardsRelation: number[],
    insight: Partial<QueryBasedInsightModel> = {}
): QueryBasedInsightModel {
    const tiles = dashboardJson.tiles.filter((tile) => !!tile.insight && tile.insight?.id === insightId)
    let tile = dashboardJson.tiles[0]
    if (tiles.length) {
        tile = tiles[0]
    }
    if (!tile.insight) {
        throw new Error('tile has no insight')
    }
    return {
        ...tile.insight,
        dashboards: dashboardsRelation,
        dashboard_tiles: dashboardsRelation.map((dashboardId) => ({ id: insight.id!, dashboard_id: dashboardId })),
        query: { ...tile.insight.query, ...insight.query, kind: (tile.insight.query?.kind || insight.query?.kind)! },
    }
}

const TEXT_TILE: DashboardTile<QueryBasedInsightModel> = {
    id: 4,
    text: { body: 'I AM A TEXT', last_modified_at: '2021-01-01T00:00:00Z' },
    layouts: {},
    color: InsightColor.Blue,
}

let tileId = 0
export const tileFromInsight = (
    insight: QueryBasedInsightModel,
    id: number = tileId++
): DashboardTile<QueryBasedInsightModel> => ({
    id: id,
    layouts: {},
    color: null,
    insight: insight,
})

export const dashboardResult = (
    dashboardId: number,
    tiles: DashboardTile<QueryBasedInsightModel>[],
    filters: Partial<DashboardFilter> = {}
): DashboardType<QueryBasedInsightModel> => {
    return {
        ...dashboardJson,
        filters: { ...dashboardJson.filters, ...filters },
        id: dashboardId,
        tiles,
    }
}

const uncached = (insight: QueryBasedInsightModel): QueryBasedInsightModel => ({
    ...insight,
    result: null,
    last_refresh: null,
})

export const boxToString = (param: string | readonly string[]): string => {
    //path params from msw can be a string or an array
    if (typeof param === 'string') {
        return param
    }
    throw new Error("this shouldn't be an array")
}

const insight800 = (): QueryBasedInsightModel => ({
    ...insightOnDashboard(800, [9, 10]),
    id: 800,
    short_id: '800' as InsightShortId,
    last_refresh: now().toISOString(),
})

describe('dashboardLogic', () => {
    let logic: ReturnType<typeof dashboardLogic.build>

    /**
     * This test setup is tightly coupled to how the API behaves
     *  (instead of being a list of mock results based on order of calls)
     *  in order to clarify the behaviour of the interacting logics it tests
     *
     * starting state
     *
     * dashboards:  5, 6, 8, 9, 10
     * insights: 175, 172, 666, 800, 999, 1001
     *
     *                  d5             d8 - i1001
     *                /    \
     *             i172    i175
     *               \      /
     *                  d6              d9 - i800 - d10
     *               /     \
     *             i666    i999
     */
    let dashboards: Record<number, DashboardType<QueryBasedInsightModel>> = {}

    beforeEach(() => {
        jest.spyOn(api, 'update')

        const insights: Record<number, QueryBasedInsightModel> = {
            172: {
                ...insightOnDashboard(172, [5, 6], {
                    query: examples.InsightRetention,
                }),
                short_id: '172' as InsightShortId,
                query_status: {
                    complete: false,
                    query_async: true,
                    results: null,
                    id: '123',
                    team_id: 2,
                    error_message: null,
                    error: false,
                },
            },
            175: { ...insightOnDashboard(175, [5, 6]), short_id: '175' as InsightShortId },
            666: {
                ...insightOnDashboard(666, [6]),
                id: 666,
                short_id: '666' as InsightShortId,
                last_refresh: now().toISOString(),
            },
            999: {
                ...insightOnDashboard(999, [6]),
                id: 999,
                short_id: '999' as InsightShortId,
                last_refresh: now().toISOString(),
            },
            1001: {
                ...insightOnDashboard(1001, [8]),
                id: 1001,
                short_id: '1001' as InsightShortId,
                last_refresh: now().toISOString(),
            },
            800: insight800(),
        }
        dashboards = {
            5: {
                ...dashboardResult(5, [tileFromInsight(insights['172']), tileFromInsight(insights['175']), TEXT_TILE]),
            },
            6: {
                ...dashboardResult(6, [
                    tileFromInsight(uncached(insights['172'])),
                    tileFromInsight(uncached(insights['175'])),
                    tileFromInsight(insights['666']),
                    tileFromInsight(insights['999']),
                ]),
            },
            8: {
                ...dashboardResult(8, [tileFromInsight(insights['1001'])]),
            },
            9: {
                ...dashboardResult(9, [tileFromInsight(insights['800']), TEXT_TILE]),
            },
            10: {
                ...dashboardResult(10, [tileFromInsight(insights['800'])]),
            },
            11: {
                ...dashboardResult(11, [], { date_from: '-24h' }),
            },
        }
        useMocks({
            get: {
                '/api/environments/:team_id/query/123/': () => [
                    200,
                    {
                        query_status: {
                            complete: true,
                        },
                    },
                ],
                '/api/environments/:team_id/dashboards/5/': { ...dashboards['5'] },
                '/api/environments/:team_id/dashboards/6/': { ...dashboards['6'] },
                '/api/environments/:team_id/dashboards/7/': () => [500, '💣'],
                '/api/environments/:team_id/dashboards/8/': { ...dashboards['8'] },
                '/api/environments/:team_id/dashboards/9/': { ...dashboards['9'] },
                '/api/environments/:team_id/dashboards/10/': { ...dashboards['10'] },
                '/api/environments/:team_id/dashboards/11/': { ...dashboards['11'] },
                '/api/environments/:team_id/dashboards/': {
                    count: 6,
                    next: null,
                    previous: null,
                    results: [
                        { ...dashboards['5'] },
                        { ...dashboards['6'] },
                        { ...dashboards['8'] },
                        { ...dashboards['9'] },
                        { ...dashboards['10'] },
                    ],
                },
                '/api/environments/:team_id/insights/1001/': () => [200, { ...insights['1001'] }],
                '/api/environments/:team_id/insights/800/': () => [200, { ...insights['800'] }],
                '/api/environments/:team_id/insights/:id/': (req) => {
                    const dashboard = req.url.searchParams.get('from_dashboard')
                    if (!dashboard) {
                        throw new Error('the logic must always add this param')
                    }
                    const matched = insights[boxToString(req.params['id'])]
                    if (!matched) {
                        return [404, null]
                    }
                    return [200, matched]
                },
            },
            post: {
                '/api/environments/:team_id/insights/cancel/': [201],
            },
            patch: {
                '/api/environments/:team_id/dashboards/:id/': async (req) => {
                    const dashboardId = typeof req.params['id'] === 'string' ? req.params['id'] : req.params['id'][0]
                    const payload = await req.json()
                    return [200, { ...dashboards[dashboardId], ...payload }]
                },
                '/api/environments/:team_id/dashboards/:id/move_tile/': async (req) => {
                    // backend updates the two dashboards and the insight
                    const jsonPayload = await req.json()
                    const { toDashboard, tile: tileToUpdate } = jsonPayload
                    const from = dashboards[Number(req.params.id)]
                    // remove the tile from the source dashboard
                    const fromIndex = from.tiles.findIndex(
                        (tile) => !!tile.insight && tile.insight.id === tileToUpdate.insight.id
                    )
                    const removedTile = from.tiles.splice(fromIndex, 1)[0]

                    // update the insight
                    const insightId = tileToUpdate.insight.id
                    const insight = insights[insightId]
                    insight.dashboards?.splice(
                        insight.dashboards?.findIndex((d) => d === from.id),
                        1
                    )
                    insight.dashboards?.push(toDashboard)

                    // add the tile to the target dashboard
                    removedTile.insight = insight
                    const targetDashboard = dashboards[toDashboard]
                    targetDashboard.tiles.push(removedTile)

                    return [200, { ...from }]
                },
                '/api/environments/:team_id/insights/:id/': async (req) => {
                    try {
                        const updates = await req.json()
                        if (typeof updates !== 'object') {
                            return [500, `this update should receive an object body not ${JSON.stringify(updates)}`]
                        }
                        const insightId = boxToString(req.params.id)

                        const starting: QueryBasedInsightModel = insights[insightId]
                        insights[insightId] = {
                            ...starting,
                            ...updates,
                        }

                        starting.dashboards?.forEach((dashboardId) => {
                            // remove this insight from any dashboard it is already on
                            dashboards[dashboardId].tiles = dashboards[dashboardId].tiles.filter(
                                (t) => !!t.insight && t.insight.id !== starting.id
                            )
                        })

                        insights[insightId].dashboards?.forEach((dashboardId: number) => {
                            // then add it to any it new references
                            dashboards[dashboardId].tiles.push(tileFromInsight(insights[insightId]))
                        })

                        return [200, insights[insightId]]
                    } catch (e) {
                        return [500, e]
                    }
                },
            },
        })
        initKeaTests()
        dashboardsModel.mount()
        insightsModel.mount()
    })

    describe('tile layouts', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
        })

        it('saving layouts creates api call with all tiles', async () => {
            await expectLogic(logic).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/dashboards/5`, {
                tiles: [
                    {
                        id: 0,
                        layouts: {},
                    },
                    {
                        id: 1,
                        layouts: {},
                    },
                    {
                        id: 4,
                        layouts: {},
                    },
                ],
                breakdown_colors: [],
                data_color_theme_id: null,
                filters: {},
                variables: {},
            })
        })
    })

    describe('moving between dashboards', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 9 })
            logic.mount()
        })

        it('only replaces the source dashboard with the target', async () => {
            jest.spyOn(api, 'update')

            const dashboardEightlogic = dashboardLogic({ id: 8 })
            dashboardEightlogic.mount()

            // insight 800 starts on dashboard 9 and 10
            // dashboard 9 has only that 1 insight
            // so moving insight 800 to dashboard 8 means dashboard 9 has no insights
            // and that insight800 is on dashboard 8 and 10
            const startingDashboard = dashboards['9']

            const tiles = startingDashboard.tiles
            const sourceTile = tiles[0]

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({
                    dashboard: truth(({ tiles }) => {
                        return tiles.length === 2 && tiles[0].insight.id === 800
                    }),
                })

            await expectLogic(dashboardEightlogic).toFinishAllListeners()

            expect(dashboardEightlogic.values.dashboard?.tiles.length).toEqual(1)
            expect(dashboardEightlogic.values.insightTiles?.map((t) => t.insight?.id)).toEqual([1001])

            await expectLogic(logic, () => {
                logic.actions.moveToDashboard(sourceTile, 9, 8, 'targetDashboard')
            })
                .toFinishAllListeners()
                .toDispatchActions(['moveToDashboardSuccess'])
                .toMatchValues({
                    dashboard: truth(({ tiles }) => {
                        return tiles.length === 1 && !!tiles[0].text
                    }),
                })

            await expectLogic(dashboardEightlogic).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                `api/environments/${MOCK_TEAM_ID}/dashboards/${9}/move_tile`,
                expect.objectContaining({ tile: sourceTile, toDashboard: 8 })
            )
        })

        it('adds tile on moveToDashboardSuccess', async () => {
            const dashboardEightlogic = dashboardLogic({ id: 8 })
            dashboardEightlogic.mount()

            await expectLogic(dashboardEightlogic)
                .toDispatchActions(['loadDashboardSuccess'])
                .toMatchValues({
                    dashboard: truth(({ tiles }) => {
                        return tiles.length === 1 && tiles[0].insight.id === 1001
                    }),
                })

            await expectLogic(dashboardEightlogic, () => {
                dashboardsModel.actions.tileMovedToDashboard({} as DashboardTile<QueryBasedInsightModel>, 8)
            }).toMatchValues({
                dashboard: truth(({ tiles }) => {
                    return tiles.length === 2
                }),
            })
        })

        it('ignores tile on moveToDashboardSuccess for a different dashboard', async () => {
            const dashboardEightlogic = dashboardLogic({ id: 8 })
            dashboardEightlogic.mount()

            await expectLogic(dashboardEightlogic)
                .toDispatchActions(['loadDashboardSuccess'])
                .toMatchValues({
                    dashboard: truth(({ tiles }) => {
                        return tiles.length === 1 && tiles[0].insight.id === 1001
                    }),
                })

            await expectLogic(dashboardEightlogic, () => {
                dashboardsModel.actions.tileMovedToDashboard({} as DashboardTile<QueryBasedInsightModel>, 10)
            }).toMatchValues({
                dashboard: truth(({ tiles }) => {
                    return tiles.length === 1
                }),
            })
        })
    })

    describe('when the dashboard API errors', () => {
        beforeEach(silenceKeaLoadersErrors)
        afterEach(resumeKeaLoadersErrors)

        beforeEach(() => {
            logic = dashboardLogic({ id: 7 })
            logic.mount()
        })

        it('allows consumers to respond', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                dashboardFailedToLoad: true,
            })
        })
    })

    describe('when a dashboard item API errors', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 8 })
            logic.mount()
        })

        it.skip('allows consumers to respond', async () => {
            // TODO: Not sure why this test is not working
            await expectLogic(logic, () => {
                // try and load dashboard items data once dashboard is loaded
                logic.actions.refreshDashboardItem({
                    tile: {
                        insight: {
                            id: 1001,
                            short_id: '1001',
                        },
                    } as any,
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    refreshStatus: { 1001: { error: true, timer: null } },
                })
        })
    })

    describe('when props id is set to a number', () => {
        beforeEach(async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        describe('on load', () => {
            it('mounts other logics', async () => {
                await expectLogic(logic).toMount([dashboardsModel, insightsModel, eventUsageLogic, teamLogic])
            })

            it('fetches dashboard items on mount', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadDashboard'])
                    .toMatchValues({
                        dashboard: null,
                        tiles: [],
                        insightTiles: [],
                        textTiles: [],
                    })
                    .toDispatchActions(['loadDashboardSuccess'])
                    .toMatchValues({
                        dashboard: expect.objectContaining(dashboards['5']),
                        tiles: truth((tiles) => tiles.length === 3),
                        insightTiles: truth((insightTiles) => insightTiles.length === 2),
                        textTiles: truth((textTiles) => textTiles.length === 1),
                        dashboardFailedToLoad: false,
                    })
            })
        })

        describe('insight refresh', () => {
            it('manual refresh reloads all insights', async () => {
                const dashboard = dashboards[5]
                const insight1 = dashboard.tiles[0].insight!
                const insight2 = dashboard.tiles[1].insight!

                await expectLogic(logic, () => {
                    logic.actions.triggerDashboardRefresh()
                })
                    .toDispatchActions([
                        // starts loading
                        'triggerDashboardRefresh',
                        'refreshDashboardItems',
                        // sets the "reloading" status
                        logic.actionCreators.setRefreshStatuses([insight1.short_id, insight2.short_id], false, true),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [insight1.short_id]: {
                                loading: false,
                                queued: true,
                                timer: null,
                            },
                            [insight2.short_id]: {
                                loading: false,
                                queued: true,
                                timer: null,
                            },
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 2,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        // and updates the action in the model
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardInsight &&
                            a.payload.insight.short_id === insight1.short_id,
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardInsight &&
                            a.payload.insight.short_id === insight2.short_id,
                        // no longer reloading
                        logic.actionCreators.setRefreshStatus(insight1.short_id, false),
                        logic.actionCreators.setRefreshStatus(insight2.short_id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [insight1.short_id]: {
                                refreshed: true,
                                timer: expect.any(Date),
                            },
                            [insight2.short_id]: {
                                refreshed: true,
                                timer: expect.any(Date),
                            },
                        },
                        refreshMetrics: {
                            completed: 2,
                            total: 2,
                        },
                    })
            })

            it('automatic refresh reloads stale insights (but not fresh ones)', async () => {
                const dashboard = dashboards[5]
                const staleInsight = {
                    ...dashboard.tiles[0].insight!,
                    cache_target_age: now().subtract(1, 'minute').toISOString(),
                }
                const freshInsight = {
                    ...dashboard.tiles[1].insight!,
                    cache_target_age: now().add(1, 'minute').toISOString(),
                }

                // patch dashboard tiles
                dashboard.tiles[0].insight = staleInsight
                dashboard.tiles[1].insight = freshInsight

                await expectLogic(logic, () => {
                    logic.actions.loadDashboard({
                        action: DashboardLoadAction.InitialLoad,
                    })
                })
                    .toDispatchActions([
                        // starts loading
                        'loadDashboard',
                        'refreshDashboardItems',
                        // sets the "reloading" status for the stale insight
                        logic.actionCreators.setRefreshStatuses([staleInsight.short_id], false, true),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [staleInsight.short_id]: {
                                loading: false,
                                queued: true,
                                timer: null,
                            },
                            [freshInsight.short_id]: undefined,
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 1,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        // and updates the action in the model
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardInsight &&
                            a.payload.insight.short_id === staleInsight.short_id,
                        // no longer reloading
                        logic.actionCreators.setRefreshStatus(staleInsight.short_id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [staleInsight.short_id]: {
                                refreshed: true,
                                timer: expect.any(Date),
                            },
                            [freshInsight.short_id]: undefined,
                        },
                        refreshMetrics: {
                            completed: 1,
                            total: 1,
                        },
                    })
            })
        })
    })

    describe('external updates', () => {
        beforeEach(async () => {
            logic = dashboardLogic({ id: 9 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const insight = logic.values.insightTiles[0].insight!
            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            expect(insight.short_id).toEqual('800')
            const query = insight.query as InsightVizNode<TrendsQuery> | undefined
            expect(query?.source?.dateRange?.date_from).toBeUndefined()
            expect(query?.source?.interval).toEqual('day')
            expect(insight.name).toEqual('donut')
            expect(logic.values.textTiles[0].text!.body).toEqual('I AM A TEXT')
        })

        it('can respond to external update of an insight on the dashboard', async () => {
            const copiedInsight = insight800()
            const insightQuery = copiedInsight.query as InsightVizNode<TrendsQuery> | undefined
            dashboardsModel.actions.updateDashboardInsight({
                ...copiedInsight,
                query: {
                    ...insightQuery,
                    source: {
                        ...insightQuery?.source,
                        dateRange: { ...insightQuery?.source?.dateRange, date_from: '-1d' },
                        interval: 'hour',
                    },
                } as InsightVizNode<TrendsQuery>,
                last_refresh: '2012-04-01T00:00:00Z',
            })

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            const query = logic.values.insightTiles[0].insight?.query as InsightVizNode<TrendsQuery> | undefined
            expect(query?.source?.dateRange?.date_from).toEqual('-1d')
            expect(query?.source?.interval).toEqual('hour')
            expect(logic.values.textTiles[0].text!.body).toEqual('I AM A TEXT')
        })

        it('can respond to external insight rename', async () => {
            expect(logic.values.dashboard?.tiles[0].color).toEqual(null)

            const copiedInsight = insight800()
            insightsModel.actions.renameInsightSuccess({
                ...copiedInsight,
                name: 'renamed',
                last_modified_at: '2021-04-01 12:00:00',
                description: 'should be ignored',
            })

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            expect(logic.values.insightTiles[0].insight!.name).toEqual('renamed')
            expect(logic.values.insightTiles[0].insight!.last_modified_at).toEqual('2021-04-01 12:00:00')
            expect(logic.values.insightTiles[0].insight!.description).toEqual(null)
            expect(logic.values.textTiles[0].text!.body).toEqual('I AM A TEXT')
        })

        it('can respond to external insight update for an insight tile that is new on this dashboard', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.updateDashboardInsight({
                    short_id: 'not_already_on_the_dashboard' as InsightShortId,
                } as QueryBasedInsightModel)
            })
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboard'])
        })
    })

    describe('text tiles', () => {
        beforeEach(async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('can remove text tiles', async () => {
            await expectLogic(logic, () => {
                logic.actions.removeTile(TEXT_TILE)
            })
                .toFinishAllListeners()
                .toDispatchActions([
                    dashboardsModel.actionTypes.tileRemovedFromDashboard,
                    logic.actionTypes.removeTileSuccess,
                ])

            expect(logic.values.textTiles).toEqual([])
        })
    })

    it('can move an insight off a dashboard', async () => {
        const nineLogic = dashboardLogic({ id: 9 })
        nineLogic.mount()
        await expectLogic(nineLogic).toFinishAllListeners()

        const fiveLogic = dashboardLogic({ id: 5 })
        fiveLogic.mount()
        await expectLogic(fiveLogic).toFinishAllListeners()

        expect(
            fiveLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: t.insight!.dashboards,
            }))
        ).toEqual([
            { dashboards: [5, 6], short_id: '172' },
            { dashboards: [5, 6], short_id: '175' },
        ])
        expect(
            nineLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: t.insight!.dashboards,
            }))
        ).toEqual([{ dashboards: [9, 10], short_id: '800' }])

        const changedInsight: QueryBasedInsightModel = { ...insight800(), dashboards: [10, 5] } // Moved from to 9 to 5
        dashboardsModel.actions.updateDashboardInsight(changedInsight, [9])

        expect(
            fiveLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: t.insight!.dashboards,
            }))
        ).toEqual([
            { dashboards: [5, 6], short_id: '172' },
            { dashboards: [5, 6], short_id: '175' }, // It's expected that 800 isn't here yet, because we expect to load it from the API for correctness
        ])
        expect(
            nineLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: t.insight!.dashboards,
            }))
        ).toEqual([])
        // Ensuring we do go back to the API for 800, which was added to dashboard 5
        expectLogic(fiveLogic).toDispatchActions(['loadDashboard']).toFinishAllListeners()
    })
})

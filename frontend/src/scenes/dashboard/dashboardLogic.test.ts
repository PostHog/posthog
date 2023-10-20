/* eslint-disable  @typescript-eslint/no-non-null-assertion */
// let tiles assert an insight is present in tests i.e. `tile!.insight` when it must be present for tests to pass
import { expectLogic, truth } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import _dashboardJson from './__mocks__/dashboard.json'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightModel,
    InsightShortId,
    InsightType,
    TextModel,
    TileLayout,
} from '~/types'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dayjs, now } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import api from 'lib/api'
import { DashboardFilter } from '~/queries/schema'

const dashboardJson = _dashboardJson as any as DashboardType

export function insightOnDashboard(
    insightId: number,
    dashboardsRelation: number[],
    insight: Partial<InsightModel> = {}
): InsightModel {
    const tiles = dashboardJson.tiles.filter((tile) => !!tile.insight && tile.insight?.id === insightId)
    let tile = dashboardJson.tiles[0] as DashboardTile
    if (tiles.length) {
        tile = tiles[0] as DashboardTile
    }
    if (!tile.insight) {
        throw new Error('tile has no insight')
    }
    return { ...tile.insight, dashboards: dashboardsRelation, filters: { ...tile.insight.filters, ...insight.filters } }
}

const TEXT_TILE: DashboardTile = {
    id: 4,
    text: { body: 'I AM A TEXT', last_modified_at: '2021-01-01T00:00:00Z' },
    layouts: {},
    color: InsightColor.Blue,
    last_refresh: '2021-01-01T00:00:00Z',
}

let tileId = 0
export const tileFromInsight = (insight: InsightModel, id: number = tileId++): DashboardTile => ({
    id: id,
    layouts: {},
    color: null,
    insight: insight,
    last_refresh: insight.last_refresh,
})

export const dashboardResult = (
    dashboardId: number,
    tiles: DashboardTile[],
    filters: Partial<DashboardFilter> = {}
): DashboardType => {
    return {
        ...dashboardJson,
        filters: { ...dashboardJson.filters, ...filters },
        id: dashboardId,
        tiles,
    }
}

const uncached = (insight: InsightModel): InsightModel => ({ ...insight, result: null, last_refresh: null })

export const boxToString = (param: string | readonly string[]): string => {
    //path params from msw can be a string or an array
    if (typeof param === 'string') {
        return param
    } else {
        throw new Error("this shouldn't be an array")
    }
}

const insight800 = (): InsightModel => ({
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
    let dashboards: Record<number, DashboardType> = {}

    beforeEach(() => {
        jest.spyOn(api, 'update')

        const insights: Record<number, InsightModel> = {
            172: {
                ...insightOnDashboard(172, [5, 6], {
                    filters: { insight: InsightType.RETENTION },
                }),
                short_id: '172' as InsightShortId,
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
            1001: { id: 1001, short_id: '1001' as InsightShortId } as unknown as InsightModel,
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
                '/api/projects/:team/dashboards/5/': { ...dashboards['5'] },
                '/api/projects/:team/dashboards/6/': { ...dashboards['6'] },
                '/api/projects/:team/dashboards/7/': () => [500, '💣'],
                '/api/projects/:team/dashboards/8/': { ...dashboards['8'] },
                '/api/projects/:team/dashboards/9/': { ...dashboards['9'] },
                '/api/projects/:team/dashboards/10/': { ...dashboards['10'] },
                '/api/projects/:team/dashboards/11/': { ...dashboards['11'] },
                '/api/projects/:team/dashboards/': {
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
                '/api/projects/:team/insights/1001/': () => [500, '💣'],
                '/api/projects/:team/insights/800/': () => [200, { ...insights['800'] }],
                '/api/projects/:team/insights/:id/': (req) => {
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
                '/api/projects/:team/insights/cancel/': [201],
            },
            patch: {
                '/api/projects/:team/dashboards/:id/': async (req) => {
                    const dashboardId = typeof req.params['id'] === 'string' ? req.params['id'] : req.params['id'][0]
                    const payload = await req.json()
                    return [200, { ...dashboards[dashboardId], ...payload }]
                },
                '/api/projects/:team/dashboards/:id/move_tile/': async (req) => {
                    // backend updates the two dashboards and the insight
                    const jsonPayload = await req.json()
                    const { toDashboard, tile: tileToUpdate } = jsonPayload
                    const from = dashboards[Number(req.params.id)]
                    // remove the tile from the source dashboard
                    const fromIndex = from.tiles.findIndex(
                        (tile) => !!tile.insight && tile.insight.id === tileToUpdate.insight.id
                    )
                    const removedTile = from.tiles.splice(fromIndex, 1)[0] as DashboardTile

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
                '/api/projects/:team/insights/:id/': async (req) => {
                    try {
                        const updates = await req.json()
                        if (typeof updates !== 'object') {
                            return [500, `this update should receive an object body not ${JSON.stringify(updates)}`]
                        }
                        const insightId = boxToString(req.params.id)

                        const starting: InsightModel = insights[insightId]
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

        it('saving layouts with no provided tiles updates all tiles', async () => {
            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveLayouts()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
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
            })
        })

        it('saving layouts with provided tiles updates only those tiles', async () => {
            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveLayouts([{ id: 1, layouts: { sm: {} as TileLayout, xs: {} as TileLayout } }])
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
                tiles: [
                    {
                        id: 1,
                        layouts: { sm: {} as TileLayout, xs: {} as TileLayout },
                    },
                ],
            })
        })
    })

    describe('when the dashboard has filters', () => {
        it('sets the filters reducer on load', async () => {
            logic = dashboardLogic({ id: 11 })
            logic.mount()

            await expectLogic(logic)
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['setDates'])
                .toMatchValues({ filters: { date_from: '-24h', date_to: null, properties: [] } })
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
            const sourceTile = tiles[0] as DashboardTile

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
                `api/projects/${MOCK_TEAM_ID}/dashboards/${9}/move_tile`,
                expect.objectContaining({ tile: sourceTile, toDashboard: 8 })
            )
        })

        it('adds tile on moveToDashboardSuccess', async () => {
            const dashboardEightlogic = dashboardLogic({ id: 8 })
            dashboardEightlogic.mount()

            await expectLogic(dashboardEightlogic)
                .toFinishAllListeners()
                .toMatchValues({
                    dashboard: truth(({ tiles }) => {
                        return tiles.length === 1 && tiles[0].insight.id === 1001
                    }),
                })

            await expectLogic(dashboardEightlogic, () => {
                dashboardsModel.actions.tileMovedToDashboard({} as DashboardTile, 8)
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
                .toFinishAllListeners()
                .toMatchValues({
                    dashboard: truth(({ tiles }) => {
                        return tiles.length === 1 && tiles[0].insight.id === 1001
                    }),
                })

            await expectLogic(dashboardEightlogic, () => {
                dashboardsModel.actions.tileMovedToDashboard({} as DashboardTile, 10)
            }).toMatchValues({
                dashboard: truth(({ tiles }) => {
                    return tiles.length === 1
                }),
            })
        })
    })

    describe('when there is no props id', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: undefined })
            logic.mount()
        })

        it('does not fetch dashboard items on mount', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadDashboardItems'])
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
                receivedErrorsFromAPI: true,
            })
        })
    })

    describe('when a dashboard item API errors', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 8 })
            logic.mount()
        })

        it('allows consumers to respond', async () => {
            await expectLogic(logic, () => {
                // try and load dashboard items data once dashboard is loaded
                logic.actions.refreshAllDashboardItemsManual()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    refreshStatus: { 1001: { error: true, timer: expect.anything() } },
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
                    .toDispatchActions(['loadDashboardItems'])
                    .toMatchValues({
                        dashboard: null,
                        tiles: [],
                        insightTiles: [],
                        textTiles: [],
                    })
                    .toDispatchActions(['loadDashboardItemsSuccess'])
                    .toMatchValues({
                        dashboard: expect.objectContaining(dashboards['5']),
                        tiles: truth((tiles) => tiles.length === 3),
                        insightTiles: truth((insightTiles) => insightTiles.length === 2),
                        textTiles: truth((textTiles) => textTiles.length === 1),
                        receivedErrorsFromAPI: false,
                    })
            })
        })

        describe('reload items', () => {
            it('reloads all items', async () => {
                await expectLogic(logic, () => {
                    logic.actions.refreshAllDashboardItemsManual()
                })
                    .toDispatchActions([
                        // starts loading
                        'refreshAllDashboardItemsManual',
                        'refreshAllDashboardItems',
                        // sets the "reloading" status
                        logic.actionCreators.setRefreshStatuses(
                            dashboards['5'].tiles.reduce((acc, curr) => {
                                if (curr.insight) {
                                    acc.push(curr.insight.short_id)
                                }
                                return acc
                            }, [] as InsightShortId[]),
                            true
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [(dashboards['5'].tiles[0] as DashboardTile).insight!.short_id]: {
                                loading: true,
                                timer: expect.anything(),
                            },
                            [(dashboards['5'].tiles[1] as DashboardTile).insight!.short_id]: {
                                loading: true,
                                timer: expect.anything(),
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
                            a.payload.insight.short_id ===
                                (dashboards['5'].tiles[1] as DashboardTile).insight!.short_id,
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardInsight &&
                            a.payload.insight.short_id ===
                                (dashboards['5'].tiles[0] as DashboardTile).insight!.short_id,
                        // no longer reloading
                        logic.actionCreators.setRefreshStatus(
                            (dashboards['5'].tiles[0] as DashboardTile).insight!.short_id,
                            false
                        ),
                        logic.actionCreators.setRefreshStatus(
                            (dashboards['5'].tiles[1] as DashboardTile).insight!.short_id,
                            false
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [(dashboards['5'].tiles[0] as DashboardTile).insight!.short_id]: {
                                refreshed: true,
                                timer: expect.anything(),
                            },
                            [(dashboards['5'].tiles[1] as DashboardTile).insight!.short_id]: {
                                refreshed: true,
                                timer: expect.anything(),
                            },
                        },
                        refreshMetrics: {
                            completed: 2,
                            total: 2,
                        },
                    })
            })

            it('reloads selected items', async () => {
                await expectLogic(logic, () => {
                    logic.actions.refreshAllDashboardItems({
                        tiles: [dashboards['5'].tiles[0] as DashboardTile],
                        action: 'refresh_manual',
                    })
                })
                    .toFinishAllListeners()
                    .toDispatchActions([
                        'refreshAllDashboardItems',
                        logic.actionCreators.setRefreshStatuses(
                            [(dashboards['5'].tiles[0] as DashboardTile).insight!.short_id],
                            true
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [(dashboards['5'].tiles[0] as DashboardTile).insight!.short_id]: {
                                loading: true,
                                timer: expect.anything(),
                            },
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 1,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardInsight &&
                            a.payload.insight.short_id ===
                                (dashboards['5'].tiles[0] as DashboardTile).insight!.short_id,
                        logic.actionCreators.setRefreshStatus(
                            (dashboards['5'].tiles[0] as DashboardTile).insight!.short_id,
                            false
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [(dashboards['5'].tiles[0] as DashboardTile).insight!.short_id]: {
                                refreshed: true,
                                timer: expect.anything(),
                            },
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
            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            expect(logic.values.insightTiles[0].insight!.short_id).toEqual('800')
            expect(logic.values.insightTiles[0].insight!.filters.date_from).toBeUndefined()
            expect(logic.values.insightTiles[0].insight!.filters.interval).toEqual('day')
            expect(logic.values.insightTiles[0].insight!.name).toEqual('donut')
            expect(logic.values.textTiles[0].text!.body).toEqual('I AM A TEXT')
        })

        it('can respond to external update of an insight on the dashboard', async () => {
            const copiedInsight = insight800()
            dashboardsModel.actions.updateDashboardInsight(
                {
                    ...copiedInsight,
                    filters: { ...copiedInsight.filters, date_from: '-1d', interval: 'hour' },
                    last_refresh: '2012-04-01T00:00:00Z',
                },
                [],
                [9]
            )

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            expect(logic.values.insightTiles[0].insight!.filters.date_from).toEqual('-1d')
            expect(logic.values.insightTiles[0].insight!.filters.interval).toEqual('hour')
            expect(logic.values.textTiles[0].text!.body).toEqual('I AM A TEXT')
            expect(logic.values.insightTiles[0]!.last_refresh).toEqual('2012-04-01T00:00:00Z')
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
                } as InsightModel)
            })
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboardItems'])
        })

        it('can respond to external insight update for a text tile', async () => {
            expect(logic.values.dashboard?.tiles).toHaveLength(2)

            await expectLogic(logic, () => {
                const updatedTile: DashboardTile = {
                    ...TEXT_TILE,
                    text: { ...TEXT_TILE.text, body: 'updated body' } as TextModel,
                }
                dashboardsModel.actions.updateDashboardTile(updatedTile, [9])
            }).toFinishAllListeners()

            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            expect(logic.values.insightTiles[0].insight!.name).toEqual('donut')
            expect(logic.values.textTiles[0].text!.body).toEqual('updated body')
        })
    })

    describe('with a half-cached dashboard', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 6 })
            logic.mount()
        })

        it('fetches dashboard items on mount', async () => {
            await expectLogic(logic)
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboardItemsSuccess'])
                .toMatchValues({
                    dashboard: truth(
                        ({ tiles }) => tiles.filter((i: DashboardTile) => i.insight?.result === null).length === 2
                    ),
                    tiles: truth((items) => items.length === 4),
                    insightTiles: truth((tiles) => tiles.length === 4),
                })
                .toDispatchActions(['refreshAllDashboardItems', 'setRefreshStatuses'])
                .toMatchValues({
                    refreshMetrics: {
                        completed: 0,
                        total: 2,
                    },
                })
                .toDispatchActions(['setRefreshStatus', 'setRefreshStatus'])
                .toMatchValues({
                    refreshMetrics: {
                        completed: 2,
                        total: 2,
                    },
                })
                .toMatchValues({
                    dashboard: truth(
                        ({ tiles }) => tiles.filter((i: DashboardTile) => i.insight?.result === null).length === 0
                    ),
                    tiles: truth((items) => items.length === 4),
                    insightTiles: truth((tiles) => tiles.length === 4),
                })
        })
    })

    describe('lastRefreshed', () => {
        it('should be the earliest refreshed dashboard', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({
                    lastRefreshed: dayjs('2021-09-21T11:48:48.444504Z'),
                })
        })

        it('should refresh all dashboards if lastRefreshed is older than 3 hours', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['refreshAllDashboardItems']).toFinishAllListeners()
        })

        it('should not refresh all dashboards if lastRefreshed is older than 3 hours but the feature flag is not set', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toNotHaveDispatchedActions(['refreshAllDashboardItems']).toFinishAllListeners()
        })

        it('should not refresh if lastRefreshed is less than 3 hours', async () => {
            logic = dashboardLogic({ id: 9 })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['loadDashboardItemsSuccess'])
                .toNotHaveDispatchedActions(['refreshAllDashboardItems'])
                .toFinishListeners()
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

        const changedTile: DashboardTile = {
            ...(nineLogic.values.dashboard?.tiles[0] as DashboardTile), // we know it isn't undefined
            insight: { ...insight800(), dashboards: [10, 5] },
        }

        dashboardsModel.actions.updateDashboardTile(changedTile, [9])

        expect(
            fiveLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: t.insight!.dashboards,
            }))
        ).toEqual([
            { dashboards: [5, 6], short_id: '172' },
            { dashboards: [5, 6], short_id: '175' },
            { dashboards: [10, 5], short_id: '800' },
        ])
        expect(
            nineLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: t.insight!.dashboards,
            }))
        ).toEqual([])
    })
})
/* eslint-enable  @typescript-eslint/no-non-null-assertion */

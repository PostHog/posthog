// let tiles assert an insight is present in tests i.e. `tile!.insight` when it must be present for tests to pass
import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic, truth } from 'kea-test-utils'
import posthog from 'posthog-js'
import type { Layout } from 'react-grid-layout'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'
import * as dashboardWidgetUtils from '@posthog/products-dashboards/frontend/utils'
import { DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE } from '@posthog/products-dashboards/frontend/widgets/constants'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs, now } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { pluralize } from 'lib/utils/strings'
import { addInsightToDashboardLogic } from 'scenes/dashboard/addInsightToDashboardModalLogic'
import { parseDashboardId } from 'scenes/dashboard/Dashboard'
import { dashboardInsightColorsModalLogic } from 'scenes/dashboard/dashboardInsightColorsModalLogic'
import { DashboardLoadAction, dashboardLogic, RefreshDashboardItemsAction } from 'scenes/dashboard/dashboardLogic'
import * as dashboardUtils from 'scenes/dashboard/dashboardUtils'
import { liveDashboardIds } from 'scenes/dashboard/liveDashboardIds'
import * as widgetFetchUtils from 'scenes/dashboard/widgetFetchUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { examples } from '~/queries/examples'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { HogQLVariable, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightShortId,
    PropertyFilterType,
    PropertyOperator,
    InsightModel,
} from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from 'products/dashboards/frontend/dashboardCustomization'
import { dashboardTileGroupChoicesLogic } from 'products/dashboards/frontend/dashboardTileGroupChoicesLogic'

import { dashboardResult, insightOnDashboard, tileFromInsight } from './dashboardLogic.testHelpers'

const TEXT_TILE: DashboardTile = {
    id: 4,
    text: { body: 'I AM A TEXT', last_modified_at: '2021-01-01T00:00:00Z' },
    layouts: {},
    color: InsightColor.Blue,
}

const WIDGET_TILE: DashboardTile = {
    id: 7,
    widget: { id: '1', widget_type: 'error_tracking_list', config: {} },
    layouts: {},
    color: null,
}

const WIDGET_TILE_WITH_CUSTOM_NAME: DashboardTile = {
    id: 8,
    widget: { id: '2', widget_type: 'error_tracking_list', config: {}, name: 'Critical errors' },
    layouts: {},
    color: null,
}

const uncached = (insight: InsightModel): InsightModel => ({
    ...insight,
    result: null,
    last_refresh: null,
})

export const boxToId = (param: string | readonly string[]): number => {
    //path params from msw can be a string or an array
    if (typeof param === 'string') {
        return parseInt(param)
    }
    throw new Error("this shouldn't be an array")
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
                    error_code: null,
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
            12: {
                ...dashboardResult(12, []),
                persisted_filters: { date_from: '-24h' },
            },
            13: {
                ...dashboardResult(13, []),
            },
            18: {
                ...dashboardResult(18, [tileFromInsight(uncached(insights['800']))]),
                persisted_filters: { date_from: '-24h' },
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
                '/api/environments/:team_id/dashboards/5/': { ...dashboards[5] },
                '/api/environments/:team_id/dashboards/6/': { ...dashboards[6] },
                '/api/environments/:team_id/dashboards/7/': () => [500, '💣'],
                '/api/environments/:team_id/dashboards/13/': () => [404, { detail: 'Not found.' }],
                '/api/environments/:team_id/dashboards/14/': () => [401, { detail: 'Authentication expired.' }],
                '/api/environments/:team_id/dashboards/15/': () => [
                    403,
                    { code: 'permission_denied', detail: 'Access denied.' },
                ],
                '/api/environments/:team_id/dashboards/16/': () => [504, { detail: 'Gateway timeout.' }],
                '/api/environments/:team_id/dashboards/8/': { ...dashboards[8] },
                '/api/environments/:team_id/dashboards/9/': { ...dashboards[9] },
                '/api/environments/:team_id/dashboards/10/': { ...dashboards[10] },
                '/api/environments/:team_id/dashboards/11/': { ...dashboards[11] },
                '/api/environments/:team_id/dashboards/12/': { ...dashboards[12] },
                '/api/environments/:team_id/dashboards/18/': { ...dashboards[18] },
                '/api/environments/:team_id/dashboards/': {
                    count: 6,
                    next: null,
                    previous: null,
                    results: [
                        { ...dashboards[5] },
                        { ...dashboards[6] },
                        { ...dashboards[8] },
                        { ...dashboards[9] },
                        { ...dashboards[10] },
                    ],
                },
                '/api/environments/:team_id/data_color_themes/': [
                    {
                        id: 1,
                        name: 'Default theme',
                        colors: Array.from({ length: 15 }, (_, i) => `#0000${String(i).padStart(2, '0')}`),
                        is_global: true,
                    },
                    { id: 123, name: 'Two-color theme', colors: ['#ff0000', '#00ff00'], is_global: false },
                ],
                '/api/environments/:team_id/insights/1001/': () => [200, { ...insights['1001'] }],
                '/api/environments/:team_id/insights/800/': () => [200, { ...insights['800'] }],
                '/api/environments/:team_id/insights/:id/': ({ request, params }) => {
                    const dashboard = new URL(request.url).searchParams.get('from_dashboard')
                    if (!dashboard) {
                        throw new Error('the logic must always add this param')
                    }
                    const matched = insights[boxToId(params.id as string | readonly string[])]
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
                '/api/environments/:team_id/dashboards/:id/': async ({ request, params }) => {
                    const dashboardId =
                        typeof params.id === 'string' ? parseInt(params.id) : parseInt((params.id as string[])[0])
                    const payload = (await request.json()) as Record<string, any>
                    return [200, { ...dashboards[dashboardId], ...payload }]
                },
                '/api/environments/:team_id/dashboards/:id/move_tile/': async ({ request, params }) => {
                    // backend updates the two dashboards and the insight
                    const jsonPayload = (await request.json()) as Record<string, any>
                    const { to_dashboard: toDashboard, tile: tileToUpdate } = jsonPayload
                    const from = dashboards[Number(params.id)]
                    // remove the tile from the source dashboard
                    const fromIndex = from.tiles.findIndex(
                        (tile) => !!tile.insight && tile.insight.id === tileToUpdate.insight.id
                    )
                    const removedTile = from.tiles.splice(fromIndex, 1)[0]

                    // update the insight
                    const insightId = tileToUpdate.insight.id
                    const insight = insights[insightId]
                    insight.dashboard_tiles = [
                        ...(insight.dashboard_tiles || []).filter((t) => t.dashboard_id !== from.id),
                        { id: removedTile.id, dashboard_id: toDashboard },
                    ]

                    // add the tile to the target dashboard
                    removedTile.insight = insight
                    const targetDashboard = dashboards[toDashboard]
                    targetDashboard.tiles.push(removedTile)

                    return [200, { ...from }]
                },
                '/api/environments/:team_id/insights/:id/': async ({ request, params }) => {
                    try {
                        const updates = await request.json()
                        if (typeof updates !== 'object') {
                            return [500, `this update should receive an object body not ${JSON.stringify(updates)}`]
                        }
                        const insightId = boxToId(params.id as string | readonly string[])

                        const starting: InsightModel = insights[insightId]
                        // like a session response, the stored insight carries its membership as tiles only
                        const { dashboards: requestedDashboards, ...rest } = updates as Partial<InsightModel>
                        const nextDashboards = requestedDashboards ?? liveDashboardIds(starting.dashboard_tiles)
                        insights[insightId] = {
                            ...starting,
                            ...rest,
                            dashboard_tiles: nextDashboards.map((dashboardId) => ({
                                id: insightId,
                                dashboard_id: dashboardId,
                            })),
                        }

                        liveDashboardIds(starting.dashboard_tiles).forEach((dashboardId) => {
                            // remove this insight from any dashboard it is already on
                            dashboards[dashboardId].tiles = dashboards[dashboardId].tiles.filter(
                                (t) => !!t.insight && t.insight.id !== starting.id
                            )
                        })

                        nextDashboards.forEach((dashboardId: number) => {
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

    describe('malformed dashboard id', () => {
        it('mounts and reports not found when id props are omitted during a scene transition', async () => {
            const invalidLogic = dashboardLogic.build()
            invalidLogic.mount()

            await expectLogic(invalidLogic).toMatchValues({ error404: true, hasInvalidDashboardId: true })
        })

        it.each([
            ['NaN', NaN],
            ['undefined', undefined as unknown as number],
            ['Infinity', Infinity],
        ])('mounts and reports not found instead of throwing when id is %s', async (_label, id) => {
            const invalidLogic = dashboardLogic({ id })
            invalidLogic.mount()
            await expectLogic(invalidLogic).toMatchValues({ error404: true, hasInvalidDashboardId: true })
        })

        it('accepts a finite numeric id', () => {
            expect(() => dashboardLogic({ id: 42 })).not.toThrow()
        })

        it('reports not found when dashboard data is supplied for an invalid id', async () => {
            const invalidLogic = dashboardLogic({ id: NaN, dashboard: dashboards[5] })
            invalidLogic.mount()

            await expectLogic(invalidLogic).toMatchValues({ error404: true, hasInvalidDashboardId: true })
        })

        it('does not load the zero dashboard sentinel', async () => {
            const zeroLogic = dashboardLogic({ id: 0 })
            zeroLogic.mount()

            await expectLogic(zeroLogic)
                .toNotHaveDispatchedActions(['loadDashboard', 'loadDashboardStreaming', 'dashboardNotFound'])
                .toMatchValues({ error404: false, hasInvalidDashboardId: false })
        })

        it.each(['12abc', '12.5', '+12', '-12', '0', '00', '000'])('rejects invalid route id %s', (id) => {
            expect(parseDashboardId(id)).toBeNaN()
        })

        it('parses a full numeric route id', () => {
            expect(parseDashboardId('12')).toBe(12)
        })
    })

    describe('tile group sections', () => {
        let target: InsightShortId

        // The band of group 'target' holds tiles 0 and 2, so on the dashboard tile 1 sits in a gap between them.
        const groupTiles = (groups: Record<string, { collapsed: boolean }>, viewerChoice?: boolean): void => {
            dashboards[5] = {
                ...dashboards[5],
                customization: { groups },
                tiles: dashboards[5].tiles.map((tile, index) => ({
                    ...tile,
                    group_key: index === 1 ? 'other' : 'target',
                    layouts: { sm: { x: 0, y: index * 2, w: 12, h: 2 } } as DashboardTile['layouts'],
                })),
            }
            target = dashboards[5].tiles[0].insight!.short_id
            if (viewerChoice !== undefined) {
                dashboardTileGroupChoicesLogic.mount()
                dashboardTileGroupChoicesLogic.actions.setTileGroupCollapsed(5, 'target', viewerChoice)
            }
        }

        const mountDashboard = async (placement?: DashboardPlacement): Promise<void> => {
            logic = dashboardLogic({ id: 5, placement })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        }

        const highlight = async (insightId: string): Promise<void> => {
            await expectLogic(logic, () => {
                router.actions.push('/dashboard/5', { highlightInsightId: insightId })
            }).toFinishAllListeners()
        }

        beforeEach(() => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_TILE_GROUP_SECTIONS], {
                [FEATURE_FLAGS.DASHBOARD_TILE_GROUP_SECTIONS]: true,
            })
            useMocks({ get: { '/api/environments/:team_id/dashboards/5/': () => [200, dashboards[5]] } })
        })

        afterEach(() => {
            localStorage.clear()
            featureFlagLogic.actions.setFeatureFlags([], {})
        })

        it.each([
            { name: 'a link opened before the dashboard loads', beforeLoad: true, viewerChoice: undefined },
            { name: 'a link followed on a loaded dashboard', beforeLoad: false, viewerChoice: undefined },
            { name: 'a group the viewer closed', beforeLoad: false, viewerChoice: true },
        ])('opens the highlighted tile group for $name', async ({ beforeLoad, viewerChoice }) => {
            groupTiles({ target: { collapsed: true }, other: { collapsed: true } }, viewerChoice)
            if (beforeLoad) {
                router.actions.push('/dashboard/5', { highlightInsightId: target })
            }
            await mountDashboard()
            if (!beforeLoad) {
                await highlight(target)
            }

            expect(logic.values.collapsedTileGroupKeys).toEqual(['other'])
        })

        it("opens a highlighted tile group without saving it as the viewer's choice", async () => {
            groupTiles({ target: { collapsed: true } })
            await mountDashboard()
            await highlight(target)

            expect(logic.values.collapsedTileGroupKeys).toEqual([])
            expect(dashboardTileGroupChoicesLogic.values.tileGroupChoices).toEqual({})
        })

        it('closes a highlighted tile group on toggle and opens it again for a new highlight', async () => {
            groupTiles({ target: { collapsed: true } })
            await mountDashboard()
            await highlight(target)

            logic.actions.toggleTileGroup('target')
            await highlight(target)
            expect(logic.values.collapsedTileGroupKeys).toEqual(['target'])

            await highlight('missing-insight')
            await highlight(target)
            expect(logic.values.collapsedTileGroupKeys).toEqual([])
        })

        it.each([
            { placement: DashboardPlacement.Dashboard, expected: ['target'] },
            { placement: DashboardPlacement.Export, expected: [] },
        ])('closes saved tile groups on the $placement placement', async ({ placement, expected }) => {
            groupTiles({ target: { collapsed: true } })
            await mountDashboard(placement)

            expect(logic.values.collapsedTileGroupKeys).toEqual(expected)
        })

        it('does not change the layout when a band grid reports the layout it was given', async () => {
            groupTiles({})
            await mountDashboard()
            const compactor = getDashboardGridCompactor(DashboardGridCompaction.Vertical)

            for (const sectionLayouts of logic.values.tileGroupSectionLayouts) {
                logic.actions.updateTileGroupSectionLayout({ sm: compactor.compact(sectionLayouts.sm ?? [], 12) })
            }

            expect(logic.values.hasUnsavedLayoutChanges).toBe(false)
        })

        describe('moving a tile between tile groups', () => {
            interface PendingSave {
                tileIds: number[]
                resolve: () => void
                reject: () => void
            }
            let pendingSaves: PendingSave[]
            let tileIds: number[]

            const groupOf = (tileId: number): string | null =>
                logic.values.tiles.find((tile) => tile.id === tileId)?.group_key ?? null
            const enterEditMode = (): void =>
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )

            beforeEach(async () => {
                const groupKeys = ['plans', 'ops', null]
                dashboards[5] = {
                    ...dashboards[5],
                    customization: { groups: { plans: { title: 'Pricing plans' }, ops: { collapsed: true } } },
                    tiles: dashboards[5].tiles.map((tile, index) => ({
                        ...tile,
                        group_key: groupKeys[index],
                        layouts: { sm: { x: 0, y: index * 2, w: 12, h: 2 } } as DashboardTile['layouts'],
                    })),
                }
                tileIds = dashboards[5].tiles.map((tile) => tile.id)
                pendingSaves = []
                // Like the server, a save answers with the saved dashboard, which lacks moves still on their way.
                jest.spyOn(api, 'update').mockImplementation((_url, data) => {
                    const payload = data as { tiles: Partial<DashboardTile>[] }
                    return new Promise((resolve, reject) =>
                        pendingSaves.push({
                            tileIds: payload.tiles.filter((entry) => 'group_key' in entry).map((entry) => entry.id!),
                            resolve: () =>
                                resolve({
                                    ...dashboards[5],
                                    tiles: dashboards[5].tiles.map((tile) => ({
                                        ...tile,
                                        ...payload.tiles.find((entry) => entry.id === tile.id),
                                    })),
                                }),
                            reject: () => reject(new Error('network down')),
                        })
                    )
                })
                await mountDashboard()
            })

            afterEach(() => {
                ;(api.update as jest.Mock).mockRestore()
            })

            const settleSaves = async (): Promise<void> => {
                pendingSaves.forEach((save) => save.resolve())
                await expectLogic(logic).toFinishAllListeners()
            }

            it.each([
                {
                    name: 'into a titled group',
                    tileIndex: 2,
                    sectionKey: 'group-plans',
                    groupKey: 'plans',
                    toast: 'Moved to the "Pricing plans" group',
                },
                // An untitled group is named by its tile count, which the move changes.
                {
                    name: 'into a closed untitled group',
                    tileIndex: 0,
                    sectionKey: 'group-ops',
                    groupKey: 'ops',
                    toast: `Moved to the "${pluralize(2, 'tile')}" group`,
                },
                {
                    name: 'out of its group',
                    tileIndex: 0,
                    sectionKey: null,
                    groupKey: null,
                    toast: 'Tile taken out of its group',
                },
            ])('in view mode saves a tile moved $name at once', async ({ tileIndex, sectionKey, groupKey, toast }) => {
                const tileId = tileIds[tileIndex]
                const successToast = jest.spyOn(lemonToast, 'success')
                const capture = jest.spyOn(posthog, 'capture')

                logic.actions.moveTileToSection(tileId, sectionKey, null, 'menu')
                await waitFor(() => expect(pendingSaves).toHaveLength(1))
                await settleSaves()

                expect(pendingSaves.map((save) => save.tileIds)).toEqual([[tileId]])
                expect(groupOf(tileId)).toBe(groupKey)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(false)
                expect(logic.values.collapsedTileGroupKeys).toEqual(['ops'])
                expect(successToast).toHaveBeenCalledWith(toast)
                expect(capture).toHaveBeenCalledWith(
                    'dashboard tile moved between groups',
                    expect.objectContaining({ method: 'menu', to_group: groupKey !== null })
                )
            })

            it.each([
                {
                    name: 'two quick moves both save',
                    firstSaves: true,
                    secondMove: { tile: 'other', target: 'group-ops', inEditMode: false },
                    expected: { first: 'ops', firstAtSavedCell: true, second: 'ops', unsaved: false, captures: 2 },
                },
                {
                    name: 'a failed first move puts back only its own tile',
                    firstSaves: false,
                    secondMove: { tile: 'other', target: 'group-ops', inEditMode: false },
                    expected: { first: 'plans', firstAtSavedCell: true, second: 'ops', unsaved: false, captures: 1 },
                },
                {
                    name: 'a failed move keeps an edit-mode move of another tile',
                    firstSaves: false,
                    secondMove: { tile: 'other', target: 'group-ops', inEditMode: true },
                    expected: { first: 'plans', firstAtSavedCell: true, second: 'ops', unsaved: true, captures: 1 },
                },
                {
                    name: 'a failed move keeps a later edit-mode move of the same tile',
                    firstSaves: false,
                    secondMove: { tile: 'same', target: null, inEditMode: true },
                    expected: { first: null, firstAtSavedCell: false, second: null, unsaved: true, captures: 1 },
                },
            ])('in view mode, $name', async ({ firstSaves, secondMove, expected }) => {
                const first = tileIds[0]
                const second = secondMove.tile === 'same' ? first : tileIds[2]
                const capture = jest.spyOn(posthog, 'capture')

                logic.actions.moveTileToSection(first, 'group-ops', null, 'menu')
                await waitFor(() => expect(pendingSaves).toHaveLength(1))
                if (secondMove.inEditMode) {
                    enterEditMode()
                }
                logic.actions.moveTileToSection(second, secondMove.target, null, 'menu')
                if (firstSaves) {
                    pendingSaves[0].resolve()
                } else {
                    pendingSaves[0].reject()
                }
                if (!secondMove.inEditMode) {
                    await waitFor(() => expect(pendingSaves).toHaveLength(2))
                }
                await settleSaves()

                const firstCell = logic.values.layouts.sm?.find((item) => item.i === String(first))
                const savedFirstCell = logic.values.savedTilePlacements[first]?.layouts?.sm
                expect(pendingSaves.map((save) => save.tileIds)).toEqual(
                    secondMove.inEditMode ? [[first]] : [[first], [second]]
                )
                expect({
                    first: groupOf(first),
                    firstAtSavedCell: firstCell?.y === savedFirstCell?.y,
                    second: groupOf(second),
                    unsaved: logic.values.hasUnsavedLayoutChanges,
                    captures: capture.mock.calls.filter(([event]) => event === 'dashboard tile moved between groups')
                        .length,
                }).toEqual(expected)
            })

            it('keeps a view-mode move made while a layout save is on its way', async () => {
                const [plansTile, , looseTile] = tileIds
                enterEditMode()
                logic.actions.moveTileToSection(looseTile, 'group-plans', { x: 0, y: 0 }, 'drag')
                logic.actions.saveLayoutChanges()
                await waitFor(() => expect(pendingSaves).toHaveLength(1))

                logic.actions.moveTileToSection(plansTile, 'group-ops', null, 'menu')
                pendingSaves[0].resolve()
                await waitFor(() => expect(pendingSaves).toHaveLength(2))
                await settleSaves()
                expect(logic.values.hasUnsavedLayoutChanges).toBe(false)

                logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                expect({ moved: groupOf(plansTile), saved: groupOf(looseTile) }).toEqual({
                    moved: 'ops',
                    saved: 'plans',
                })
            })

            it.each([
                { name: 'shows the move', afterDiscard: 'nothing', expectedGroup: 'ops', groupSaves: 1 },
                {
                    name: 'shows the move in a new edit session',
                    afterDiscard: 'edit',
                    expectedGroup: 'ops',
                    groupSaves: 1,
                },
                {
                    name: 'keeps a newer saved drag of the tile',
                    afterDiscard: 'drag and save',
                    expectedGroup: 'plans',
                    groupSaves: 2,
                },
            ])(
                'when a view-mode move saves after a discard put the tile back, $name',
                async ({ afterDiscard, expectedGroup, groupSaves }) => {
                    const plansTile = tileIds[0]
                    logic.actions.moveTileToSection(plansTile, 'group-ops', null, 'menu')
                    await waitFor(() => expect(pendingSaves).toHaveLength(1))
                    enterEditMode()
                    logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                    expect(groupOf(plansTile)).toBe('plans')

                    if (afterDiscard !== 'nothing') {
                        enterEditMode()
                    }
                    if (afterDiscard === 'drag and save') {
                        logic.actions.stageLayouts({
                            sm: (logic.values.layouts.sm ?? []).map((item) =>
                                item.i === String(plansTile) ? { ...item, y: 1 } : item
                            ),
                        })
                        logic.actions.saveLayoutChanges()
                        pendingSaves[0].resolve()
                        await waitFor(() => expect(pendingSaves).toHaveLength(2))
                    }
                    await settleSaves()

                    expect({
                        group: groupOf(plansTile),
                        unsaved: logic.values.hasUnsavedLayoutChanges,
                        groupSaves: pendingSaves.filter((save) => save.tileIds.includes(plansTile)).length,
                    }).toEqual({ group: expectedGroup, unsaved: false, groupSaves })
                }
            )

            it('runs a layout save queued behind a newer one without an error', async () => {
                const [, opsTile, looseTile] = tileIds
                const errorToast = jest.spyOn(lemonToast, 'error')
                logic.actions.moveTileToSection(opsTile, null, null, 'menu')
                await waitFor(() => expect(pendingSaves).toHaveLength(1))
                enterEditMode()
                logic.actions.moveTileToSection(looseTile, 'group-plans', { x: 0, y: 0 }, 'drag')

                logic.actions.saveEditModeChanges('layout')
                logic.actions.saveEditModeChanges('layout')
                pendingSaves[0].resolve()
                await waitFor(() => expect(pendingSaves).toHaveLength(2))
                await settleSaves()

                expect(errorToast).not.toHaveBeenCalled()
                expect(pendingSaves.map((save) => save.tileIds)).toEqual([[opsTile], [looseTile]])
                expect(groupOf(looseTile)).toBe('plans')
            })

            it('sends a queued layout save after the dashboard closes', async () => {
                const [, opsTile, looseTile] = tileIds
                logic.actions.moveTileToSection(opsTile, null, null, 'menu')
                await waitFor(() => expect(pendingSaves).toHaveLength(1))
                enterEditMode()
                logic.actions.moveTileToSection(looseTile, 'group-plans', { x: 0, y: 0 }, 'drag')

                logic.actions.saveEditModeChanges('layout')
                logic.unmount()
                pendingSaves[0].resolve()

                await waitFor(() => expect(pendingSaves).toHaveLength(2))
                expect(pendingSaves.map((save) => save.tileIds)).toEqual([[opsTile], [looseTile]])
                pendingSaves[1].resolve()
                await waitFor(() => expect(logic.isMounted()).toBe(false))
            })

            it.each([
                { finish: 'save', saveFails: false, expectedGroup: 'plans', unsaved: false },
                { finish: 'save', saveFails: true, expectedGroup: 'plans', unsaved: true },
                { finish: 'cancel', saveFails: false, expectedGroup: null, unsaved: false },
            ])(
                'in edit mode keeps a dragged tile unsaved until $finish (save fails: $saveFails)',
                async ({ finish, saveFails, expectedGroup, unsaved }) => {
                    const looseTile = tileIds[2]
                    const capture = jest.spyOn(posthog, 'capture')
                    enterEditMode()

                    logic.actions.moveTileToSection(looseTile, 'group-plans', { x: 0, y: 0 }, 'drag')

                    expect(pendingSaves).toHaveLength(0)
                    expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
                    expect(logic.values.tileGroupSectionLayouts[0].sm).toContainEqual(
                        expect.objectContaining({ i: String(looseTile), y: 0 })
                    )
                    expect(capture).toHaveBeenCalledWith(
                        'dashboard tile moved between groups',
                        expect.objectContaining({ method: 'drag', from_group: false, to_group: true })
                    )

                    if (finish === 'save') {
                        logic.actions.saveLayoutChanges()
                        await waitFor(() => expect(pendingSaves).toHaveLength(1))
                        if (saveFails) {
                            pendingSaves[0].reject()
                        }
                    } else {
                        logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                    }
                    await settleSaves()

                    expect(pendingSaves.map((save) => save.tileIds)).toEqual(finish === 'save' ? [[looseTile]] : [])
                    expect(groupOf(looseTile)).toBe(expectedGroup)
                    expect(logic.values.hasUnsavedLayoutChanges).toBe(unsaved)
                }
            )
        })

        it('keeps the changes of two bands that report in the same tick', async () => {
            groupTiles({})
            await mountDashboard()
            const [targetBand, otherBand] = logic.values.tileGroupSectionLayouts.map((layouts) => layouts.sm ?? [])
            const narrow = (layout: Layout): Layout => layout.map((item) => ({ ...item, w: 6 }))

            logic.actions.updateTileGroupSectionLayout({ sm: narrow(targetBand) })
            logic.actions.updateTileGroupSectionLayout({ sm: narrow(otherBand) })

            expect(logic.values.layouts.sm?.map((item) => item.w)).toEqual([6, 6, 6])
        })

        describe('loading closed groups', () => {
            let refreshInsight: jest.SpiedFunction<typeof dashboardUtils.getInsightWithRetry>
            let fetchRunWidgetsMock: jest.SpiedFunction<typeof widgetFetchUtils.fetchRunWidgets>

            const loads = (shortId: InsightShortId): Parameters<typeof dashboardUtils.getInsightWithRetry>[] =>
                refreshInsight.mock.calls.filter((call) => call[1].short_id === shortId)

            const toggle = async (): Promise<void> => {
                await expectLogic(logic, () => logic.actions.toggleTileGroup('target')).toFinishAllListeners()
            }

            const hangUntilAborted = (signal: AbortSignal | undefined): Promise<never> =>
                new Promise((_, reject) =>
                    signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
                )

            beforeEach(() => {
                refreshInsight = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation((_teamId, insight) => Promise.resolve(insight))
                fetchRunWidgetsMock = jest
                    .spyOn(widgetFetchUtils, 'fetchRunWidgets')
                    .mockResolvedValue([
                        { tile_id: WIDGET_TILE.id, widget_type: 'error_tracking_list', result: {}, error: null },
                    ])
            })

            afterEach(() => {
                refreshInsight.mockRestore()
                fetchRunWidgetsMock.mockRestore()
            })

            it.each([
                {
                    name: 'a manual refresh',
                    refresh: () => logic.actions.triggerDashboardRefresh(),
                    mode: 'force_blocking',
                    dateFrom: undefined,
                },
                // The preview has not finished, so settingsForRefresh still holds the saved filters.
                {
                    name: 'a filter preview',
                    refresh: () => logic.actions.setDates('-7d', null),
                    mode: 'blocking',
                    dateFrom: '-7d',
                },
            ])('loads a closed group on open with the settings of $name', async ({ refresh, mode, dateFrom }) => {
                groupTiles({ target: { collapsed: true } })
                await mountDashboard()
                const visible = dashboards[5].tiles[1].insight!.short_id
                refreshInsight.mockImplementation((...args) =>
                    args[1].short_id === visible ? hangUntilAborted(args[5]?.signal) : Promise.resolve(args[1])
                )

                refresh()
                await expectLogic(logic).toDispatchActions(['setWaitingTileRefresh'])
                expect(loads(target)).toHaveLength(0)

                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['clearWaitingTileRefresh'])

                const [[, , , , refreshMode, , filters]] = loads(target)
                expect(refreshMode).toBe(mode)
                expect(filters?.date_from).toBe(dateFrom)
                expect(logic.values.waitingTileRefresh).toBeNull()
                await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
            })

            it('settles a filter preview when every insight sits in a closed group', async () => {
                groupTiles({ target: { collapsed: true }, other: { collapsed: true } })
                await mountDashboard()

                await expectLogic(logic, () => logic.actions.setDates('-7d', null)).toFinishAllListeners()

                expect(loads(target)).toHaveLength(0)
                expect(logic.values.previewedDashboardSettings?.filters.date_from).toBe('-7d')
                expect(logic.values.breakdownValuesIncomplete).toBe(true)
            })

            it.each([
                {
                    name: 'its first load failed',
                    holdBack: async (): Promise<void> => {
                        refreshInsight.mockRejectedValueOnce(new Error('Queries are busy'))
                        await toggle()
                        await toggle()
                    },
                    expectedLoads: ['blocking', 'blocking'],
                },
                {
                    name: 'the viewer cancelled a refresh',
                    holdBack: async (): Promise<void> => {
                        refreshInsight.mockImplementationOnce((...args) => hangUntilAborted(args[5]?.signal))
                        logic.actions.triggerDashboardRefresh()
                        await expectLogic(logic).toDispatchActions(['setRefreshStatus'])
                        await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
                    },
                    expectedLoads: ['force_blocking'],
                },
            ])('loads a closed group on open after $name', async ({ holdBack, expectedLoads }) => {
                groupTiles({ target: { collapsed: true } })
                await mountDashboard()
                await holdBack()
                expect(logic.values.waitingTileRefresh?.tileIds).toEqual([dashboards[5].tiles[0].id])

                await toggle()

                expect(loads(target).map((call) => call[4])).toEqual(expectedLoads)
                expect(logic.values.waitingTileRefresh).toBeNull()
            })

            it('loads a closed group that a highlight link opens', async () => {
                groupTiles({ target: { collapsed: true } })
                await mountDashboard()
                expect(loads(target)).toHaveLength(0)

                await highlight(target)

                expect(loads(target)).toHaveLength(1)
                expect(logic.values.waitingTileRefresh).toBeNull()
            })

            it.each([
                { name: 'the viewer closes and opens it again', open: () => logic.actions.toggleTileGroup('target') },
                {
                    name: 'a highlight link opens it',
                    open: () => router.actions.push('/dashboard/5', { highlightInsightId: target }),
                },
            ])('loads each tile of a group once when $name during its load', async ({ open }) => {
                groupTiles({ target: { collapsed: true } })
                dashboards[5].tiles.push({ ...WIDGET_TILE, group_key: 'target' })
                await mountDashboard()
                refreshInsight.mockImplementation((...args) => hangUntilAborted(args[5]?.signal))
                fetchRunWidgetsMock.mockImplementation((_projectId, _dashboardId, _tileIds, options) =>
                    hangUntilAborted(options?.signal)
                )

                open()
                await expectLogic(logic).toDispatchActions(['refreshTileGroup', 'setWidgetRefreshStatuses'])
                logic.actions.toggleTileGroup('target')
                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['refreshTileGroup'])

                expect(logic.values.collapsedTileGroupKeys).toEqual([])
                expect(loads(target)).toHaveLength(1)
                expect(fetchRunWidgetsMock).toHaveBeenCalledTimes(1)
                await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
            })

            it('loads a widget in a closed group on open', async () => {
                groupTiles({ target: { collapsed: true } })
                dashboards[5].tiles.push({ ...WIDGET_TILE, group_key: 'target' })
                await mountDashboard()
                expect(fetchRunWidgetsMock).not.toHaveBeenCalled()

                await toggle()

                expect(logic.values.widgetResultsByTileId[WIDGET_TILE.id]?.result).toEqual({})
                expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.error).toBeNull()
            })

            it('a filter preview neither aborts nor repeats the widget load of an opened group', async () => {
                groupTiles({ target: { collapsed: true } })
                dashboards[5].tiles.push({ ...WIDGET_TILE, group_key: 'target' })
                await mountDashboard()
                let finishWidgetLoad: () => void = () => {}
                fetchRunWidgetsMock.mockImplementationOnce(
                    (_projectId, _dashboardId, _tileIds, options) =>
                        new Promise((resolve, reject) => {
                            options?.signal?.addEventListener('abort', () =>
                                reject(new DOMException('Aborted', 'AbortError'))
                            )
                            finishWidgetLoad = () =>
                                resolve([
                                    {
                                        tile_id: WIDGET_TILE.id,
                                        widget_type: 'error_tracking_list',
                                        result: {},
                                        error: null,
                                    },
                                ])
                        })
                )
                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['setWidgetRefreshStatuses'])

                logic.actions.setDates('-7d', null)
                await expectLogic(logic).toDispatchActions(['abortAnyRunningQuery', 'setPreviewedDashboardSettings'])
                finishWidgetLoad()
                await expectLogic(logic).toFinishAllListeners()

                expect(fetchRunWidgetsMock).toHaveBeenCalledTimes(1)
                expect(logic.values.widgetResultsByTileId[WIDGET_TILE.id]?.result).toEqual({})
                expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.error).toBeNull()
            })

            it.each([
                { name: 'cancels the refresh', stop: () => logic.actions.cancelDashboardRefresh(), loading: false },
                { name: 'refreshes again', stop: () => logic.actions.triggerDashboardRefresh(), loading: true },
            ])('stops a widget load without an error when the viewer $name', async ({ stop, loading }) => {
                groupTiles({})
                dashboards[5].tiles.push(WIDGET_TILE)
                await mountDashboard()
                fetchRunWidgetsMock.mockImplementation((_projectId, _dashboardId, _tileIds, options) =>
                    hangUntilAborted(options?.signal)
                )
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
                await expectLogic(logic).toDispatchActions(['setWidgetRefreshStatuses'])

                await expectLogic(logic, stop).toDispatchActions(['stopWidgetRefreshes'])

                expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]).toMatchObject({ loading, error: null })
                fetchRunWidgetsMock.mockResolvedValue([])
                await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
            })

            it('adds an opened group to the "X out of Y" count of a running refresh', async () => {
                groupTiles({ target: { collapsed: true } })
                await mountDashboard()
                const visible = dashboards[5].tiles[1].insight!.short_id
                refreshInsight.mockImplementation((...args) =>
                    args[1].short_id === visible ? hangUntilAborted(args[5]?.signal) : Promise.resolve(args[1])
                )
                logic.actions.triggerDashboardRefresh()
                await expectLogic(logic).toDispatchActions(['setWaitingTileRefresh'])
                expect(logic.values.refreshMetrics).toEqual({ completed: 0, total: 1 })

                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['clearWaitingTileRefresh'])

                expect(logic.values.refreshMetrics).toEqual({ completed: 1, total: 2 })
                await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
            })

            it('keeps a group waiting when the viewer cancels its load, and loads it on the next open', async () => {
                groupTiles({ target: { collapsed: true } })
                await mountDashboard()
                refreshInsight.mockImplementationOnce((...args) => hangUntilAborted(args[5]?.signal))
                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['setRefreshStatus'])

                await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
                expect(logic.values.waitingTileRefresh?.tileIds).toEqual([dashboards[5].tiles[0].id])
                await toggle()
                await toggle()

                expect(loads(target)).toHaveLength(2)
                expect(logic.values.waitingTileRefresh).toBeNull()
            })

            it.each([
                { name: 'insight tiles', widgetsPerTile: 0 },
                { name: 'insight and widget tiles', widgetsPerTile: 1 },
            ])(
                'runs at most four loads at once when the viewer opens several groups during a refresh of $name',
                async ({ widgetsPerTile }) => {
                    const groupKeys = ['a', 'b', 'c']
                    const insightTile = dashboards[5].tiles[1]
                    const tile = (id: number, groupKey?: string): DashboardTile => ({
                        ...insightTile,
                        id,
                        group_key: groupKey,
                        insight: { ...insightTile.insight!, id, short_id: `${id}` as InsightShortId },
                    })
                    const widgetTile = (id: number, groupKey?: string): DashboardTile => ({
                        ...WIDGET_TILE,
                        id,
                        group_key: groupKey,
                    })
                    const tilesIn = (groupKey: string | undefined, offset: number): DashboardTile[] =>
                        Array.from({ length: 4 }, (_, index) => [
                            tile(offset + index, groupKey),
                            ...(widgetsPerTile ? [widgetTile(offset + 50 + index, groupKey)] : []),
                        ]).flat()
                    dashboards[5] = {
                        ...dashboards[5],
                        customization: {
                            groups: Object.fromEntries(groupKeys.map((groupKey) => [groupKey, { collapsed: true }])),
                        },
                        tiles: [
                            ...tilesIn(undefined, 1000),
                            ...groupKeys.flatMap((groupKey, index) => tilesIn(groupKey, 2000 + index * 100)),
                        ],
                    }
                    await mountDashboard()

                    let running = 0
                    let maxRunning = 0
                    const finishers: (() => void)[] = []
                    const track = <T>(signal: AbortSignal | undefined, value: T): Promise<T> =>
                        new Promise((resolve, reject) => {
                            let settled = false
                            const settleWith = (finish: () => void) => (): void => {
                                if (!settled) {
                                    settled = true
                                    running--
                                    finish()
                                }
                            }
                            running++
                            maxRunning = Math.max(maxRunning, running)
                            signal?.addEventListener(
                                'abort',
                                settleWith(() => reject(new DOMException('Aborted', 'AbortError')))
                            )
                            finishers.push(settleWith(() => resolve(value)))
                        })
                    refreshInsight.mockImplementation((...args) => track(args[5]?.signal, args[1]))
                    fetchRunWidgetsMock.mockImplementation((_projectId, _dashboardId, tileIds, options) =>
                        track(
                            options?.signal,
                            tileIds.map((tileId) => ({
                                tile_id: tileId,
                                widget_type: 'error_tracking_list' as const,
                                result: {},
                                error: null,
                            }))
                        )
                    )
                    refreshInsight.mockClear()

                    logic.actions.triggerDashboardRefresh()
                    groupKeys.forEach((groupKey) => logic.actions.toggleTileGroup(groupKey))
                    for (let round = 0; round < 100 && (finishers.length > 0 || round < 2); round++) {
                        finishers.shift()?.()
                        await new Promise((resolve) => setTimeout(resolve, 0))
                    }
                    await expectLogic(logic).toFinishAllListeners()

                    expect(maxRunning).toBe(4)
                    expect(new Set(refreshInsight.mock.calls.map((call) => call[1].short_id)).size).toBe(16)
                    expect(logic.values.waitingTileRefresh).toBeNull()
                }
            )

            it('keeps an opened group waiting when the viewer cancels a filter preview that took over its load', async () => {
                groupTiles({ target: { collapsed: true } })
                await mountDashboard()
                refreshInsight.mockImplementation((...args) => hangUntilAborted(args[5]?.signal))
                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['setRefreshStatus'])
                logic.actions.setDates('-7d', null)
                await expectLogic(logic).toDispatchActions(['abortAnyRunningQuery'])

                await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
                expect(logic.values.waitingTileRefresh?.tileIds).toEqual([dashboards[5].tiles[0].id])
                refreshInsight.mockImplementation((_teamId, insight) => Promise.resolve(insight))
                await toggle()
                await toggle()

                expect(loads(target)).toHaveLength(3)
                expect(logic.values.waitingTileRefresh).toBeNull()
            })

            it('drops a group load that a filter change supersedes while every group is closed', async () => {
                groupTiles({ target: { collapsed: true }, other: { collapsed: true } })
                await mountDashboard()
                let finishOldLoad: () => void = () => {}
                refreshInsight.mockImplementationOnce(
                    (...args) =>
                        new Promise((resolve, reject) => {
                            args[5]?.signal?.addEventListener('abort', () =>
                                reject(new DOMException('Aborted', 'AbortError'))
                            )
                            finishOldLoad = () => resolve({ ...args[1], result: ['old filters'] })
                        })
                )
                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['setRefreshStatus'])
                logic.actions.toggleTileGroup('target')

                logic.actions.setDates('-7d', null)
                finishOldLoad()
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.insightTiles[0].insight?.result).not.toEqual(['old filters'])
                expect(logic.values.waitingTileRefresh).toMatchObject({
                    tileIds: expect.arrayContaining([dashboards[5].tiles[0].id]),
                    settings: { filters: { date_from: '-7d' } },
                })
                await toggle()
                expect(loads(target).map((call) => call[6]?.date_from)).toEqual([undefined, '-7d'])
            })

            it('loads an open group again after an update refresh aborts its forced load', async () => {
                groupTiles({ target: { collapsed: true } })
                dashboards[5].tiles[0].insight!.cache_target_age = now().add(1, 'hour').toISOString()
                dashboards[5].tiles[1].insight!.cache_target_age = now().subtract(1, 'hour').toISOString()
                await mountDashboard()
                await expectLogic(logic, () => logic.actions.triggerDashboardRefresh()).toFinishAllListeners()
                refreshInsight.mockImplementationOnce((...args) => hangUntilAborted(args[5]?.signal))
                logic.actions.toggleTileGroup('target')
                await expectLogic(logic).toDispatchActions(['refreshTileGroup', 'setRefreshStatus'])

                await expectLogic(logic, () =>
                    logic.actions.refreshDashboardItems({ action: DashboardLoadAction.Update })
                )
                    .toDispatchActions(['refreshTileGroup'])
                    .toFinishAllListeners()

                expect(loads(target).map((call) => call[4])).toEqual(['force_blocking', 'force_blocking'])
                expect(logic.values.waitingTileRefresh).toBeNull()
            })

            it.each([
                { cancelPoint: 'after the group dispatch', expectedLoads: 2 },
                { cancelPoint: 'before the group dispatch', expectedLoads: 1 },
            ])(
                'keeps an open group queued during an update refresh, and a cancel $cancelPoint stops its reload',
                async ({ cancelPoint, expectedLoads }) => {
                    groupTiles({ target: { collapsed: true } })
                    dashboards[5].tiles[0].insight!.cache_target_age = now().add(1, 'hour').toISOString()
                    dashboards[5].tiles[1].insight!.cache_target_age = now().subtract(1, 'hour').toISOString()
                    await mountDashboard()
                    await expectLogic(logic, () => logic.actions.triggerDashboardRefresh()).toFinishAllListeners()
                    refreshInsight.mockImplementation((...args) => hangUntilAborted(args[5]?.signal))
                    logic.actions.toggleTileGroup('target')
                    await expectLogic(logic).toDispatchActions(['refreshTileGroup', 'setRefreshStatus'])

                    if (cancelPoint === 'after the group dispatch') {
                        await expectLogic(logic, () =>
                            logic.actions.refreshDashboardItems({ action: DashboardLoadAction.Update })
                        ).toDispatchActions(['refreshTileGroup'])
                        expect(logic.values.refreshStatus[target]).toMatchObject({ queued: true })

                        await expectLogic(logic, () => logic.actions.cancelDashboardRefresh()).toFinishAllListeners()
                    } else {
                        await expectLogic(logic, () =>
                            logic.actions.refreshDashboardItems({ action: DashboardLoadAction.Update })
                        ).toDispatchActions(['abortAnyRunningQuery'])

                        await expectLogic(logic, () => logic.actions.cancelDashboardRefresh())
                            .delay(5)
                            .toFinishAllListeners()
                            .toNotHaveDispatchedActions(['refreshTileGroup'])
                        expect(Object.values(logic.values.refreshStatus).filter((status) => status.queued)).toEqual([])
                    }

                    expect(loads(target)).toHaveLength(expectedLoads)
                    expect(logic.values.waitingTileRefresh?.tileIds).toContain(dashboards[5].tiles[0].id)
                }
            )

            it('an update refresh with nothing stale keeps a manual refresh running', async () => {
                groupTiles({ target: { collapsed: true } })
                dashboards[5].tiles[1].insight!.cache_target_age = now().add(1, 'hour').toISOString()
                await mountDashboard()
                const visible = dashboards[5].tiles[1].insight!.short_id
                let finishForcedLoad: () => void = () => {}
                refreshInsight.mockImplementation(
                    (...args) =>
                        new Promise((resolve, reject) => {
                            args[5]?.signal?.addEventListener('abort', () =>
                                reject(new DOMException('Aborted', 'AbortError'))
                            )
                            finishForcedLoad = () => resolve({ ...args[1], result: ['forced'] })
                        })
                )
                logic.actions.triggerDashboardRefresh()
                await expectLogic(logic).toDispatchActions(['setRefreshStatus'])

                await expectLogic(logic, () => {
                    logic.actions.refreshDashboardItems({ action: DashboardLoadAction.Update })
                    finishForcedLoad()
                })
                    .toFinishAllListeners()
                    .toNotHaveDispatchedActions(['abortQuery'])

                expect(loads(visible).map((call) => call[4])).toEqual(['force_blocking'])
                expect(logic.values.insightTiles[1].insight?.result).toEqual(['forced'])
            })

            it.each([
                { group: 'closed', collapsed: true, counts: false },
                { group: 'open', collapsed: false, counts: true },
            ])(
                'counts a stale tile in a $group group toward refreshing the dashboard: $counts',
                async ({ collapsed, counts }) => {
                    const blockRefresh = !counts
                    const forcesRefresh = counts
                    groupTiles({ target: { collapsed } })
                    await mountDashboard()
                    const [staleTile, freshTile] = logic.values.insightTiles
                    await expectLogic(logic, () => {
                        for (const [tile, lastRefresh] of [
                            [staleTile, now().subtract(1, 'day')],
                            [freshTile, now()],
                        ] as const) {
                            dashboardsModel.actions.updateDashboardInsight(
                                { ...tile.insight!, last_refresh: lastRefresh.toISOString() },
                                undefined,
                                5
                            )
                        }
                        logic.actions.updateDashboardLastRefresh(now())
                    }).toFinishAllListeners()

                    expect(logic.values.blockRefresh).toBe(blockRefresh)
                    logic.actions.forceRefreshIfStale()
                    await Promise.resolve()
                    if (forcesRefresh) {
                        await expectLogic(logic).toDispatchActions(['triggerDashboardRefresh'])
                    } else {
                        await expectLogic(logic).toNotHaveDispatchedActions(['triggerDashboardRefresh'])
                    }
                }
            )
        })
    })

    describe('tile layouts', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
        })

        it('keeps the layouts reference stable when a tile refresh changes results but not geometry', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const initialLayouts = logic.values.layouts
            const firstTile = logic.values.dashboard!.tiles[0]

            await expectLogic(logic, () => {
                // A refresh response: same insight, new object identity and results, untouched layouts.
                dashboardsModel.actions.updateDashboardInsight({
                    ...firstTile.insight!,
                    result: [{ count: 42 }],
                })
            }).toFinishAllListeners()

            expect(logic.values.tiles[0].insight!.result).toEqual([{ count: 42 }])
            expect(logic.values.layouts).toBe(initialLayouts)
        })

        it('previews tile spacing immediately and persists only the final choice', async () => {
            await expectLogic(logic).toFinishAllListeners()
            ;(api.update as jest.Mock).mockClear()
            const reportTileDensityConfigured = jest.spyOn(
                eventUsageLogic.actions,
                'reportDashboardTileDensityConfigured'
            )
            jest.useFakeTimers()

            try {
                logic.actions.setDashboardTileSpacing('tight')
                logic.actions.saveDashboardTileSpacing('tight')
                logic.actions.setDashboardTileSpacing('relaxed')
                logic.actions.saveDashboardTileSpacing('relaxed')

                expect(logic.values.dashboard?.customization?.tile_spacing).toBe('relaxed')
                expect(api.update).not.toHaveBeenCalled()

                await jest.advanceTimersByTimeAsync(750)
                await expectLogic(logic).toFinishAllListeners()

                expect(api.update).toHaveBeenCalledTimes(1)
                expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
                    layout_compaction: DashboardGridCompaction.Vertical,
                    grid_spacing: 'relaxed',
                })
                expect(reportTileDensityConfigured).toHaveBeenCalledWith('relaxed')
            } finally {
                jest.useRealTimers()
            }
        })

        it('reports the tile density when reset to standard', async () => {
            await expectLogic(logic).toFinishAllListeners()
            const reportTileDensityConfigured = jest.spyOn(
                eventUsageLogic.actions,
                'reportDashboardTileDensityConfigured'
            )
            jest.useFakeTimers()

            try {
                logic.actions.saveDashboardTileSpacing('standard')

                await jest.advanceTimersByTimeAsync(750)
                await expectLogic(logic).toFinishAllListeners()

                expect(reportTileDensityConfigured).toHaveBeenCalledWith('standard')
            } finally {
                jest.useRealTimers()
            }
        })

        it('previews layout compaction immediately and persists only the final choice', async () => {
            await expectLogic(logic).toFinishAllListeners()
            ;(api.update as jest.Mock).mockClear()
            jest.useFakeTimers()

            try {
                logic.actions.setDashboardGridCompaction(DashboardGridCompaction.Vertical)
                logic.actions.saveDashboardGridCompaction(DashboardGridCompaction.Vertical)
                logic.actions.setDashboardGridCompaction(DashboardGridCompaction.Horizontal)
                logic.actions.saveDashboardGridCompaction(DashboardGridCompaction.Horizontal)

                expect(logic.values.dashboard?.customization?.layout_compaction).toBe(
                    DashboardGridCompaction.Horizontal
                )
                expect(api.update).not.toHaveBeenCalled()

                await jest.advanceTimersByTimeAsync(750)
                await expectLogic(logic).toFinishAllListeners()

                expect(api.update).toHaveBeenCalledTimes(1)
                expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
                    layout_compaction: DashboardGridCompaction.Horizontal,
                    grid_spacing: 'standard',
                })
            } finally {
                jest.useRealTimers()
            }
        })

        it('persists the latest movement mode after a save is already in flight', async () => {
            await expectLogic(logic).toFinishAllListeners()
            let resolveFirstSave: (dashboard: DashboardType) => void = () => {
                throw new Error('First save resolver is unavailable')
            }
            const firstSave = new Promise<DashboardType>((resolve) => {
                resolveFirstSave = resolve
            })
            ;(api.update as jest.Mock).mockImplementationOnce(() => firstSave)
            jest.useFakeTimers()

            try {
                logic.actions.setDashboardGridCompaction(DashboardGridCompaction.Horizontal)
                logic.actions.saveDashboardGridCompaction(DashboardGridCompaction.Horizontal)
                await jest.advanceTimersByTimeAsync(750)

                logic.actions.setDashboardGridCompaction(DashboardGridCompaction.Stable)
                logic.actions.saveDashboardGridCompaction(DashboardGridCompaction.Stable)
                await jest.advanceTimersByTimeAsync(750)

                resolveFirstSave(logic.values.dashboard!)
                await jest.advanceTimersByTimeAsync(750)
                await expectLogic(logic).toFinishAllListeners()

                expect(api.update).toHaveBeenLastCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
                    layout_compaction: DashboardGridCompaction.Stable,
                    grid_spacing: 'standard',
                })
            } finally {
                jest.useRealTimers()
            }
        })

        it('saving without changes does not call api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()

            expect(api.update).not.toHaveBeenCalled()
        })

        it('saving after layout change calls api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const initialDashboard = logic.values.dashboard
            expect(initialDashboard).not.toBeNull()

            const firstTile = initialDashboard!.tiles[0]
            const currentLayouts = logic.values.layouts
            const modifiedLayouts: any = {
                ...currentLayouts,
                sm: currentLayouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }

            await expectLogic(logic, () => {
                logic.actions.updateLayouts(modifiedLayouts)
                logic.actions.setBreakdownColorConfig({
                    breakdownValue: 'x',
                    breakdownType: 'event',
                    colorToken: 'preset-1',
                })
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    tiles: expect.any(Array),
                })
            )
            const payload = (api.update as jest.Mock).mock.calls.at(-1)[1]
            expect(payload).not.toHaveProperty('breakdown_colors')
            expect(payload).not.toHaveProperty('data_color_theme_id')
            expect(logic.values.hasUnsavedColorChanges).toBe(true)
        })

        it('keeps saved settings when an older layout save finishes later', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const staleLayoutResponse = logic.values.dashboard!
            let finishLayoutSave: (dashboard: DashboardType) => void = () => {
                throw new Error('Layout save resolver is unavailable')
            }
            const layoutSave = new Promise<DashboardType>((resolve) => {
                finishLayoutSave = resolve
            })
            jest.spyOn(api, 'update')
                .mockReturnValueOnce(layoutSave)
                .mockImplementationOnce(async () => ({
                    ...logic.values.dashboard!,
                    persisted_filters: { date_from: '-7d' },
                }))

            const firstTile = logic.values.dashboard!.tiles[0]
            const modifiedLayouts = {
                ...logic.values.layouts,
                sm: logic.values.layouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }
            logic.actions.updateLayouts(modifiedLayouts)
            logic.actions.saveLayoutChanges()

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
                logic.actions.saveDashboardChanges()
            }).toDispatchActions(['saveDashboardChangesSuccess'])

            finishLayoutSave(staleLayoutResponse)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dashboard?.persisted_filters).toEqual({ date_from: '-7d' })
        })

        it('saves dashboard settings only when requested', async () => {
            await expectLogic(logic).toFinishAllListeners()
            const successToast = jest.spyOn(lemonToast, 'success')

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            jest.spyOn(api, 'update').mockResolvedValueOnce({
                ...logic.values.dashboard!,
                persisted_filters: logic.values.effectiveEditBarFilters,
            })

            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
                filters: expect.objectContaining({ date_from: '-7d' }),
                variables: {},
            })
            expect(logic.values.dashboard?.persisted_filters).toEqual(expect.objectContaining({ date_from: '-7d' }))
            expect(successToast).toHaveBeenCalledWith('Dashboard changes saved')
        })

        it('counts each added property filter', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setProperties([
                    {
                        key: 'browser',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                    { key: 'os', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: 'macOS' },
                ])
            }).toFinishAllListeners()

            expect(logic.values.changedFilterCount).toBe(2)
        })

        it('clears the unsaved state when a filter returns to inherit', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setInterval('week')
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')

            await expectLogic(logic, () => {
                logic.actions.setInterval(null)
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsState).toBe('saved')
            expect(logic.values.dashboardSettingsChanges).toEqual([])
        })

        it('saves a compare filter override through the draft/save round-trip', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setCompareFilter({ compare: true, compare_to: '-1m' })
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsDraft?.filters).toEqual(
                expect.objectContaining({ compareFilter: { compare: true, compare_to: '-1m' } })
            )
            expect(logic.values.effectiveEditBarFilters.compareFilter).toEqual({ compare: true, compare_to: '-1m' })
            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')

            jest.spyOn(api, 'update').mockResolvedValueOnce({
                ...logic.values.dashboard!,
                persisted_filters: logic.values.effectiveEditBarFilters,
            })

            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/5`, {
                filters: expect.objectContaining({ compareFilter: { compare: true, compare_to: '-1m' } }),
                variables: {},
            })
            expect(logic.values.dashboard?.persisted_filters).toEqual(
                expect.objectContaining({ compareFilter: { compare: true, compare_to: '-1m' } })
            )
            expect(logic.values.dashboardSettingsState).toBe('saved')
        })

        it('clears the unsaved state when the compare filter returns to inherit', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setCompareFilter({ compare: false })
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')

            await expectLogic(logic, () => {
                logic.actions.setCompareFilter(null)
            }).toFinishAllListeners()

            expect(logic.values.effectiveEditBarFilters.compareFilter).toBeNull()
            expect(logic.values.dashboardSettingsState).toBe('saved')
            expect(logic.values.dashboardSettingsChanges).toEqual([])
        })

        it('does not treat embedded context filters as unsaved dashboard filters', async () => {
            await expectLogic(logic).toFinishAllListeners()
            ;(api.update as jest.Mock).mockClear()

            await expectLogic(logic, () => {
                logic.actions.setExternalFilters({
                    properties: [
                        {
                            key: '$group_0',
                            type: PropertyFilterType.EventMetadata,
                            operator: PropertyOperator.Exact,
                            value: 'group-1',
                        },
                    ],
                })
            }).toFinishAllListeners()

            expect(logic.values.effectiveEditBarFilters.properties).toEqual([
                expect.objectContaining({ key: '$group_0', value: 'group-1' }),
            ])
            expect(logic.values.filtersDirty).toBe(false)
            expect(logic.values.filterChanges).toEqual([])
            expect(logic.values.dashboardSettingsState).toBe('saved')

            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(api.update).not.toHaveBeenCalled()
        })

        it('saving a layout change does not persist temporary filters', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const firstTile = logic.values.dashboard!.tiles[0]
            const currentLayouts = logic.values.layouts
            const modifiedLayouts: any = {
                ...currentLayouts,
                sm: currentLayouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
                logic.actions.updateLayouts(modifiedLayouts)
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            const payload = (api.update as jest.Mock).mock.calls.at(-1)[1]
            expect(payload).toEqual(expect.objectContaining({ tiles: expect.any(Array) }))
            expect(payload).not.toHaveProperty('filters')
        })

        it('saving a layout change keeps unsaved filters in filter edit mode', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
                logic.actions.setDates('-7d', null)
                logic.actions.saveLayout()
            }).toFinishAllListeners()

            expect(logic.values.urlFilters).toEqual(expect.objectContaining({ date_from: '-7d' }))
            expect(logic.values.dashboard?.persisted_filters || {}).toEqual({})
            expect(logic.values.dashboardEditing).toEqual({ filters: true, layout: false })
            expect(logic.values.layoutEditMode).toBe(false)
            expect(logic.values.filtersDirty).toBe(true)
        })

        it('saving a layout change with no unsaved settings leaves edit mode', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
                logic.actions.saveLayout()
            }).toFinishAllListeners()

            expect(logic.values.dashboardMode).toBeNull()
            expect(logic.values.layoutEditMode).toBe(false)
            expect(logic.values.filterEditModeActive).toBe(false)
        })

        const filterEditExitCases: [string, () => void][] = [
            ['saving them', () => logic.actions.saveDashboardChanges()],
            ['discarding them', () => logic.actions.discardDashboardChanges()],
            ['undoing them by hand', () => logic.actions.setInterval(null)],
        ]

        it.each(filterEditExitCases)('leaves filter edit mode after %s', async (_name, resolveChanges) => {
            await expectLogic(logic).toFinishAllListeners()
            const update = jest.spyOn(api, 'update').mockResolvedValue({
                ...logic.values.dashboard!,
                persisted_filters: { interval: 'week' },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: false },
                        DashboardEventSource.DashboardFilters
                    )
                    logic.actions.setInterval('week')
                }).toFinishAllListeners()

                expect(logic.values.dashboardEditing).toEqual({ filters: true, layout: false })

                await expectLogic(logic, resolveChanges).toFinishAllListeners()

                expect(logic.values.dashboardSettingsState).toBe('saved')
                expect(logic.values.dashboardMode).toBeNull()
            } finally {
                update.mockRestore()
            }
        })

        it('stays in layout editing when a filter change is saved', async () => {
            await expectLogic(logic).toFinishAllListeners()
            const update = jest.spyOn(api, 'update').mockResolvedValue({
                ...logic.values.dashboard!,
                persisted_filters: { interval: 'week' },
            })

            try {
                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                    logic.actions.setInterval('week')
                    logic.actions.saveDashboardChanges()
                }).toFinishAllListeners()

                expect(logic.values.dashboardSettingsState).toBe('saved')
                expect(logic.values.dashboardEditing).toEqual({ filters: true, layout: true })
                expect(logic.values.layoutEditMode).toBe(true)
            } finally {
                update.mockRestore()
            }
        })

        it('keeps layout editing after a filter change', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            expect(logic.values.dashboardEditing).toEqual({ filters: true, layout: true })
            expect(logic.values.layoutEditMode).toBe(true)
        })

        it('cancelling layout editing keeps auto-previewed filter changes', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: false },
                    DashboardEventSource.DashboardFilters
                )
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            expect(logic.values.urlFilters).toEqual(expect.objectContaining({ date_from: '-7d' }))

            await expectLogic(logic, () => {
                logic.actions.cancelLayoutEdit()
            }).toFinishAllListeners()

            expect(logic.values.dashboardMode).toBeNull()
            expect(logic.values.dashboardSettingsDraft?.filters).toEqual(expect.objectContaining({ date_from: '-7d' }))
            expect(logic.values.filtersDirty).toBe(true)
            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')
        })

        it('cancelling layout editing keeps unapplied filter changes', async () => {
            const autoPreviewLimit = jest.replaceProperty(dashboardUtils, 'AUTO_PREVIEW_TILE_LIMIT', 1)

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.canAutoPreview).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsDraft?.filters).toEqual(expect.objectContaining({ date_from: '-7d' }))

            await expectLogic(logic, () => {
                logic.actions.cancelLayoutEdit()
            }).toFinishAllListeners()

            expect(logic.values.dashboardMode).toBeNull()
            expect(logic.values.dashboardSettingsDraft?.filters).toEqual(expect.objectContaining({ date_from: '-7d' }))
            expect(logic.values.filtersDirty).toBe(true)

            autoPreviewLimit.restore()
        })

        it('saving current filters does not refresh tiles again', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            })
                .toDispatchActions(['saveDashboardChanges', 'saveDashboardChangesSuccess'])
                .toFinishAllListeners()
        })

        it.each([
            [34, true],
            [35, false],
        ])('previews filter changes automatically with %i insights: %s', async (insightCount, autoPreview) => {
            await expectLogic(logic).toFinishAllListeners()
            const dashboard = {
                ...dashboards[5],
                tiles: [
                    ...Array.from({ length: insightCount }, (_, index) => ({
                        ...dashboards[5].tiles[0],
                        id: index + 100,
                        layouts: {},
                    })),
                    TEXT_TILE,
                    WIDGET_TILE,
                ],
            }
            logic.unmount()
            logic = dashboardLogic({ id: 5, dashboard })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const refresh = jest
                .spyOn(dashboardUtils, 'getInsightWithRetry')
                .mockImplementation(async (_teamId, insight) => insight)
            const capture = jest.spyOn(posthog, 'capture').mockClear()

            try {
                await expectLogic(logic, () => {
                    logic.actions.setDates('-7d', null)
                }).toFinishAllListeners()

                expect(refresh.mock.calls.length > 0).toBe(autoPreview)
                expect(logic.values.showApplyFiltersBanner).toBe(!autoPreview)
                const change = capture.mock.calls.find(([event]) => event === 'dashboard filters changed')?.[1]
                expect(change).toEqual(
                    expect.objectContaining({
                        filter_change_id: expect.any(String),
                        total_tile_count: insightCount,
                        can_auto_preview: autoPreview,
                    })
                )
                expect(capture.mock.calls.some(([event]) => event === 'dashboard refreshed')).toBe(autoPreview)
                if (!autoPreview) {
                    refresh.mockClear()
                    jest.spyOn(api, 'update').mockResolvedValueOnce({
                        ...logic.values.dashboard!,
                        persisted_filters: { date_from: '-7d' },
                        persisted_variables: {},
                    })

                    await expectLogic(logic, () => {
                        logic.actions.saveDashboardChanges()
                    }).toFinishAllListeners()

                    expect(refresh).toHaveBeenCalled()
                }
                expect(capture).toHaveBeenCalledWith(
                    'dashboard refreshed',
                    expect.objectContaining({
                        filter_change_id: change!.filter_change_id,
                        filter_change_duration_ms: expect.any(Number),
                        all_insights_succeeded: true,
                    })
                )
            } finally {
                refresh.mockRestore()
            }
        })

        it('keeps metric variable definitions out of refresh analytics', async () => {
            await expectLogic(logic).toFinishAllListeners()
            const refresh = jest
                .spyOn(dashboardUtils, 'getInsightWithRetry')
                .mockImplementation(async (_teamId, insight) => insight)
            const capture = jest.spyOn(posthog, 'capture').mockClear()

            try {
                await expectLogic(logic, () => {
                    logic.actions.setMetricVariables([
                        { name: 'env', source: 'sql', query: 'SELECT private_value', current: { values: ['a'] } },
                    ])
                }).toFinishAllListeners()

                const refreshes = capture.mock.calls.filter(([event]) =>
                    ['dashboard refreshed', 'dashboard insight refreshed'].includes(event)
                )
                expect(refreshes.length).toBeGreaterThan(0)
                expect(JSON.stringify(refreshes)).not.toContain('private_value')
            } finally {
                refresh.mockRestore()
            }
        })

        it('refreshes a large builtin dashboard on a variable change, since it has no Preview button', async () => {
            const autoPreviewLimit = jest.replaceProperty(dashboardUtils, 'AUTO_PREVIEW_TILE_LIMIT', 0)
            logic.unmount()
            logic = dashboardLogic({ id: 5, dashboard: dashboards[5], placement: DashboardPlacement.Builtin })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            try {
                await expectLogic(logic, () => {
                    logic.actions.setMetricVariables([{ name: 'env', source: 'custom', current: { values: ['a'] } }])
                }).toDispatchActions([
                    logic.actionCreators.refreshDashboardItems({
                        action: RefreshDashboardItemsAction.Preview,
                        forceRefresh: false,
                        previewUnsavedFilters: true,
                    }),
                ])
            } finally {
                autoPreviewLimit.restore()
            }
        })

        it('keeps combined auto-preview filters after a page reload, then clears and saves them', async () => {
            const sevenTileDashboard = {
                ...dashboards[5],
                tiles: Array.from({ length: 7 }, (_, index) => ({
                    ...dashboards[5].tiles[0],
                    id: index + 100,
                    layouts: {},
                })),
            }
            logic.unmount()
            logic = dashboardLogic({ id: 5, dashboard: sevenTileDashboard })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.canAutoPreview).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setProperties([
                    {
                        key: 'browser',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                ])
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setBreakdownFilter({ breakdown: '$browser', breakdown_type: 'event' })
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setInterval('week')
            }).toFinishAllListeners()

            const filters = {
                date_from: '-7d',
                properties: [
                    {
                        key: 'browser',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                ],
                breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
                interval: 'week',
            }

            expect(logic.values.urlFilters).toEqual(expect.objectContaining(filters))

            logic.unmount()
            logic = dashboardLogic({ id: 5, dashboard: sevenTileDashboard })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.effectiveEditBarFilters).toEqual(expect.objectContaining(filters))

            await expectLogic(logic, () => {
                logic.actions.discardDashboardChanges()
            }).toFinishAllListeners()

            expect(logic.values.urlFilters).toEqual({})
            expect(logic.values.filtersDirty).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.setDates('-1d', null)
            }).toFinishAllListeners()

            jest.spyOn(api, 'update').mockResolvedValueOnce({
                ...sevenTileDashboard,
                persisted_filters: { date_from: '-1d' },
            })
            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(logic.values.dashboard?.persisted_filters).toEqual({ date_from: '-1d' })
            expect(logic.values.urlFilters).toEqual({})
        })

        it('keeps unapplied filters separate from layout cancellation and layout saving', async () => {
            const autoPreviewLimit = jest.replaceProperty(dashboardUtils, 'AUTO_PREVIEW_TILE_LIMIT', 8)
            const nineTileDashboard: DashboardType = {
                ...dashboards[5],
                tiles: Array.from({ length: 9 }, (_, index) => ({
                    ...dashboards[5].tiles[0],
                    id: index + 200,
                    layouts: {
                        sm: { i: String(index + 200), x: index, y: 0, w: 1, h: 1 },
                        xs: { i: String(index + 200), x: 0, y: index, w: 1, h: 1 },
                    },
                })),
            }
            logic.unmount()
            logic = dashboardLogic({ id: 5, dashboard: nineTileDashboard })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.canAutoPreview).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setProperties([
                    {
                        key: 'browser',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                ])
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setBreakdownFilter({ breakdown: '$browser', breakdown_type: 'event' })
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.setInterval('week')
                logic.actions.setFilterTestAccounts(true)
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsDraft?.filters).toEqual(
                expect.objectContaining({
                    date_from: '-7d',
                    properties: [expect.objectContaining({ key: 'browser', value: 'Chrome' })],
                    breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
                    interval: 'week',
                    filterTestAccounts: true,
                })
            )
            expect(logic.values.urlFilters).toEqual(
                expect.objectContaining({
                    date_from: '-7d',
                    properties: [expect.objectContaining({ key: 'browser', value: 'Chrome' })],
                    breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
                    interval: 'week',
                    filterTestAccounts: true,
                })
            )

            logic.unmount()
            logic = dashboardLogic({ id: 5, dashboard: nineTileDashboard })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.currentDashboardSettings.filters).toEqual(
                expect.objectContaining({
                    date_from: '-7d',
                    properties: [expect.objectContaining({ key: 'browser', value: 'Chrome' })],
                    breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
                    interval: 'week',
                    filterTestAccounts: true,
                })
            )
            expect(logic.values.previewedDashboardSettings?.filters).toEqual(
                expect.objectContaining({
                    date_from: '-7d',
                    properties: [expect.objectContaining({ key: 'browser', value: 'Chrome' })],
                    breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' },
                    interval: 'week',
                    filterTestAccounts: true,
                })
            )
            expect(logic.values.loadingPreview).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.previewDashboardChanges()
            }).toFinishAllListeners()

            expect(logic.values.currentDashboardSettings.filters).toEqual(expect.objectContaining({ date_from: '-7d' }))

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
            }).toFinishAllListeners()

            const firstTile = logic.values.dashboard!.tiles[0]
            const changedLayouts = {
                ...logic.values.layouts,
                sm: logic.values.layouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }
            await expectLogic(logic, () => {
                logic.actions.updateLayouts(changedLayouts)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.cancelLayoutEdit()
            }).toFinishAllListeners()

            expect(logic.values.currentDashboardSettings.filters).toEqual(expect.objectContaining({ date_from: '-7d' }))
            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.updateLayouts(changedLayouts)
            }).toFinishAllListeners()

            ;(api.update as jest.Mock).mockClear()
            ;(api.update as jest.Mock).mockResolvedValueOnce({
                ...nineTileDashboard,
                persisted_filters: logic.values.effectiveEditBarFilters,
            })
            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
            expect(logic.values.dashboard?.tiles[0].layouts).toEqual(
                changedLayouts.sm?.[0] ? { sm: changedLayouts.sm[0] } : {}
            )

            ;(api.update as jest.Mock).mockResolvedValueOnce({
                ...nineTileDashboard,
                persisted_filters: { date_from: '-7d' },
            })
            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenLastCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.not.objectContaining({ filters: expect.anything() })
            )
            expect(logic.values.dashboard?.persisted_filters).toEqual(expect.objectContaining({ date_from: '-7d' }))
            expect(logic.values.urlFilters).toEqual({})
            expect(logic.values.dashboardSettingsDraft).toBeNull()

            autoPreviewLimit.restore()
        })

        it('saving after breakdown color change calls api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const firstTile = logic.values.dashboard!.tiles[0]
            const currentLayouts = logic.values.layouts
            const modifiedLayouts: any = {
                ...currentLayouts,
                sm: currentLayouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }

            await expectLogic(logic, () => {
                logic.actions.updateLayouts(modifiedLayouts)
                logic.actions.setBreakdownColorConfig({
                    breakdownValue: 'x',
                    breakdownType: 'event',
                    colorToken: 'preset-1',
                })
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveDashboardColorChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    breakdown_colors: expect.arrayContaining([
                        expect.objectContaining({ breakdownValue: 'x', colorToken: 'preset-1' }),
                    ]),
                })
            )
            const payload = (api.update as jest.Mock).mock.calls.at(-1)[1]
            expect(payload).not.toHaveProperty('tiles')
            expect(logic.values.dashboard!.tiles[0].layouts?.sm?.x).toBe(modifiedLayouts.sm[0].x)
            expect(logic.values.savedTilePlacements[firstTile.id]?.layouts).toEqual(firstTile.layouts)
            expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
        })

        it('discarding edit mode reverts unsaved color edits', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownColorConfig({
                    breakdownValue: 'x',
                    breakdownType: 'event',
                    colorToken: 'preset-1',
                })
                logic.actions.setDataColorThemeId(123)
            }).toFinishAllListeners()

            expect(
                logic.values.effectiveBreakdownColors.some((c: { breakdownValue: string }) => c.breakdownValue === 'x')
            ).toBe(true)
            expect(logic.values.dataColorThemeId).toBe(123)
            expect(logic.values.hasUnsavedColorChanges).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }).toFinishAllListeners()

            expect(
                logic.values.effectiveBreakdownColors.some((c: { breakdownValue: string }) => c.breakdownValue === 'x')
            ).toBe(false)
            expect(logic.values.dataColorThemeId).toBe(logic.values.dashboard?.data_color_theme_id ?? null)
            expect(logic.values.hasUnsavedColorChanges).toBe(false)
        })

        it('exiting edit mode via the colors modal save source persists color changes', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: false },
                    DashboardEventSource.DashboardInsightColorsModal
                )
                logic.actions.setBreakdownColorConfig({
                    breakdownValue: 'x',
                    breakdownType: 'event',
                    colorToken: 'preset-1',
                })
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardInsightColorsModal)
            })
                .toDispatchActions(['saveEditModeChanges', 'saveEditModeChangesSuccess'])
                .toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    breakdown_colors: expect.arrayContaining([
                        expect.objectContaining({ breakdownValue: 'x', colorToken: 'preset-1' }),
                    ]),
                })
            )
        })

        it('auto-assigns colors to multi-tile breakdown values only behind the dashboard colors flag', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const [firstInsight, secondInsight] = logic.values
                .dashboard!.tiles.filter((t) => !!t.insight)
                .map((t) => t.insight!)
            const withBreakdowns = (insight: typeof firstInsight, breakdownValues: string[]): typeof firstInsight => ({
                ...insight,
                dashboard_tiles: [{ id: 1, dashboard_id: 5 }],
                result: breakdownValues.map((breakdown_value) => ({
                    action: { order: 0 },
                    breakdown_value: [breakdown_value],
                })),
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: { kind: NodeKind.TrendsQuery, series: [] },
                } as InsightVizNode<TrendsQuery>,
            })

            await expectLogic(logic, () => {
                dashboardsModel.actions.updateDashboardInsight(withBreakdowns(firstInsight, ['Chrome', 'Firefox']))
                dashboardsModel.actions.updateDashboardInsight(withBreakdowns(secondInsight, ['Chrome']))
            }).toFinishAllListeners()

            expect(logic.values.effectiveBreakdownColors).toEqual([])

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS]: true,
            })

            // Chrome appears on both tiles; Firefox is unique to one tile and keeps
            // position-based colors, so it gets no dashboard-wide entry
            expect(logic.values.effectiveBreakdownColors).toEqual([
                expect.objectContaining({ breakdownValue: 'Chrome', colorToken: 'preset-1', source: 'auto' }),
            ])
        })

        it('wraps auto-assigned colors at the active theme palette size', async () => {
            await expectLogic(logic).toFinishAllListeners()

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS]: true,
            })

            const tileInsights = logic.values.dashboard!.tiles.filter((t) => !!t.insight).map((t) => t.insight!)
            await expectLogic(logic, () => {
                for (const tileInsight of tileInsights) {
                    dashboardsModel.actions.updateDashboardInsight({
                        ...tileInsight,
                        dashboard_tiles: [{ id: 1, dashboard_id: 5 }],
                        result: [
                            { action: { order: 0 }, breakdown_value: ['Chrome'] },
                            { action: { order: 0 }, breakdown_value: ['Firefox'] },
                            { action: { order: 0 }, breakdown_value: ['Safari'] },
                        ],
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: { kind: NodeKind.TrendsQuery, series: [] },
                        } as InsightVizNode<TrendsQuery>,
                    })
                }
                logic.actions.setDataColorThemeId(123)
            }).toFinishAllListeners()

            expect(logic.values.effectiveBreakdownColors).toEqual([
                expect.objectContaining({ breakdownValue: 'Chrome', colorToken: 'preset-1' }),
                expect.objectContaining({ breakdownValue: 'Firefox', colorToken: 'preset-2' }),
                // wraps at the two-color theme's palette size, not at the default 15
                expect.objectContaining({ breakdownValue: 'Safari', colorToken: 'preset-1' }),
            ])
        })

        it('saving while tiles load persists unsaved pins but neither materializes nor prunes auto colors', async () => {
            await expectLogic(logic).toFinishAllListeners()

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS]: true,
            })

            const tileInsight = logic.values.dashboard!.tiles.find((t) => !!t.insight)!.insight!
            await expectLogic(logic, () => {
                dashboardsModel.actions.updateDashboardInsight({
                    ...tileInsight,
                    dashboard_tiles: [{ id: 1, dashboard_id: 5 }],
                    result: [{ action: { order: 0 }, breakdown_value: ['Chrome'] }],
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { kind: NodeKind.TrendsQuery, series: [] },
                    } as InsightVizNode<TrendsQuery>,
                })
                logic.actions.setBreakdownColorConfig({
                    breakdownValue: 'pinned',
                    breakdownType: 'event',
                    colorToken: 'preset-5',
                })
            }).toFinishAllListeners()

            // hold a tile in a loading state, so the visible breakdown values are incomplete
            logic.actions.setRefreshStatus(tileInsight.short_id, true)
            expect(logic.values.itemsLoading).toBe(true)

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveDashboardColorChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    // only the pin — no auto entry materialized from the partially loaded tiles
                    breakdown_colors: [expect.objectContaining({ breakdownValue: 'pinned', colorToken: 'preset-5' })],
                })
            )
        })

        it('keeps shared auto colors when a failed refresh leaves a tile without results', async () => {
            await expectLogic(logic).toFinishAllListeners()

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS]: true,
            })

            const [firstInsight, secondInsight] = logic.values
                .dashboard!.tiles.filter((t) => !!t.insight)
                .map((t) => t.insight!)
            const withBreakdownQuery = (
                insight: typeof firstInsight,
                breakdownValues: string[] | null
            ): typeof firstInsight => ({
                ...insight,
                dashboard_tiles: [{ id: 1, dashboard_id: 5 }],
                result: breakdownValues
                    ? breakdownValues.map((breakdown_value) => ({ action: { order: 0 }, breakdown_value }))
                    : null,
                query: {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [],
                        breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                    },
                } as InsightVizNode<TrendsQuery>,
            })

            await expectLogic(logic, () => {
                // one loaded tile showing the value, one in the state a failed refresh leaves
                // behind: a breakdown query whose insight never got results, while itemsLoading
                // settles back to false
                dashboardsModel.actions.updateDashboardInsight(withBreakdownQuery(firstInsight, ['Chrome', 'Firefox']))
                dashboardsModel.actions.updateDashboardInsight(withBreakdownQuery(secondInsight, null))
                // the auto entry an earlier save materialized while both tiles shared 'Chrome'
                logic.actions.setBreakdownColorConfig({
                    breakdownValue: 'Chrome',
                    breakdownType: 'event',
                    colorToken: 'preset-1',
                    source: 'auto',
                })
            }).toFinishAllListeners()

            expect(logic.values.itemsLoading).toBe(false)
            // Chrome only looks single-tile because the failed tile's values are unknown
            expect(logic.values.effectiveBreakdownColors).toContainEqual(
                expect.objectContaining({ breakdownValue: 'Chrome', colorToken: 'preset-1', source: 'auto' })
            )

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveDashboardColorChanges()
            }).toFinishAllListeners()

            // the entry survives the save instead of being pruned from the partial tile set
            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    breakdown_colors: [
                        expect.objectContaining({ breakdownValue: 'Chrome', colorToken: 'preset-1', source: 'auto' }),
                    ],
                })
            )
        })

        it('saving after theme change calls api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDataColorThemeId(123)
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveDashboardColorChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    data_color_theme_id: 123,
                })
            )
        })

        it('confirms a real save with a success toast', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const firstTile = logic.values.dashboard!.tiles[0]
            const currentLayouts = logic.values.layouts
            const modifiedLayouts: any = {
                ...currentLayouts,
                sm: currentLayouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }

            await expectLogic(logic, () => {
                logic.actions.updateLayouts(modifiedLayouts)
            }).toFinishAllListeners()

            const successToast = jest.spyOn(lemonToast, 'success')

            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()

            expect(successToast).toHaveBeenCalledWith('Dashboard saved')
        })

        it.each([
            {
                name: 'a failed layout save',
                act: async (): Promise<void> => {
                    const firstTile = logic.values.dashboard!.tiles[0]
                    logic.actions.stageLayouts({
                        sm: logic.values.layouts.sm?.map((layout) =>
                            layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 1 } : layout
                        ),
                    })
                    jest.spyOn(api, 'update').mockRejectedValueOnce(new Error('network down'))
                    logic.actions.saveLayoutChanges()
                },
                unsaved: true,
            },
            {
                name: 'a duplicated tile',
                act: async (): Promise<void> => {
                    const sourceTile = logic.values.dashboard!.tiles[0]
                    jest.spyOn(api, 'update').mockResolvedValueOnce({
                        ...logic.values.dashboard!,
                        tiles: [
                            ...logic.values.dashboard!.tiles,
                            { ...sourceTile, id: 999, layouts: { sm: { x: 0, y: 99, w: 6, h: 5 } } },
                        ],
                    })
                    logic.actions.duplicateTile(sourceTile)
                },
                unsaved: false,
            },
        ])('counts $name as saved only when the server has it', async ({ act, unsaved }) => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, act)
                .toFinishAllListeners()
                .toNotHaveDispatchedActions([dashboardsModel.actionTypes.updateDashboardSuccess])

            expect(logic.values.hasUnsavedLayoutChanges).toBe(unsaved)
        })

        it('does not show a success toast when exiting edit mode with no changes', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const successToast = jest.spyOn(lemonToast, 'success')

            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()

            expect(successToast).not.toHaveBeenCalled()
        })

        it('discarding edit mode restores original layouts', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const initialDashboard = logic.values.dashboard
            expect(initialDashboard).not.toBeNull()

            const firstTile = initialDashboard!.tiles[0]
            const originalLayouts = logic.values.savedTilePlacements[firstTile.id]?.layouts

            expect(originalLayouts).not.toBeUndefined()

            const currentLayouts = logic.values.layouts
            const modifiedLayouts: any = {
                ...currentLayouts,
                sm: currentLayouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                ),
            }

            await expectLogic(logic, () => {
                logic.actions.updateLayouts(modifiedLayouts)
            }).toFinishAllListeners()

            const editedTileLayouts = logic.values.dashboard?.tiles.find((t) => t.id === firstTile.id)?.layouts
            expect(editedTileLayouts).not.toEqual(originalLayouts)

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }).toFinishAllListeners()

            const restoredTileLayouts = logic.values.dashboard?.tiles.find((t) => t.id === firstTile.id)?.layouts
            expect(restoredTileLayouts).toEqual(originalLayouts)
        })

        describe('layoutEditMode', () => {
            it('enters edit mode without layout editing when filters change', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: false },
                        DashboardEventSource.DashboardFilters
                    )
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        dashboardEditing: { filters: true, layout: false },
                        layoutEditMode: false,
                    })
            })

            it('enables layout editing for explicit layout edit sources', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        dashboardEditing: { filters: true, layout: true },
                        layoutEditMode: true,
                    })
            })

            it('clears layout editing when exiting edit mode', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                }).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        dashboardEditing: null,
                        layoutEditMode: false,
                    })
            })

            it('reports filter changes separately from layout edit mode entry', async () => {
                const reportFiltersChanged = jest.spyOn(eventUsageLogic.actions, 'reportDashboardFiltersChanged')
                const reportLayoutEditEntered = jest.spyOn(
                    eventUsageLogic.actions,
                    'reportDashboardLayoutEditModeEntered'
                )
                const reportModeToggled = jest.spyOn(eventUsageLogic.actions, 'reportDashboardModeToggled')

                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: false },
                        DashboardEventSource.DashboardFilters
                    )
                }).toFinishAllListeners()

                expect(reportLayoutEditEntered).not.toHaveBeenCalled()
                expect(reportModeToggled).not.toHaveBeenCalled()

                await expectLogic(logic, () => {
                    logic.actions.setDates('-7d', null)
                }).toFinishAllListeners()

                expect(reportFiltersChanged).toHaveBeenCalledWith(
                    expect.objectContaining({ id: 5 }),
                    'date',
                    expect.objectContaining({ date_from: '-7d', date_to: null })
                )

                reportFiltersChanged.mockClear()
                reportLayoutEditEntered.mockClear()
                reportModeToggled.mockClear()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                }).toFinishAllListeners()

                expect(reportLayoutEditEntered).toHaveBeenCalledWith(
                    expect.objectContaining({ id: 5 }),
                    DashboardEventSource.SceneCommonButtons,
                    1
                )
                expect(reportModeToggled).not.toHaveBeenCalled()
                expect(reportFiltersChanged).not.toHaveBeenCalled()

                reportFiltersChanged.mockRestore()
                reportLayoutEditEntered.mockRestore()
                reportModeToggled.mockRestore()
            })

            it('filter edits preserve layout editing', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        layoutEditMode: true,
                    })

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.DashboardFilters
                    )
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        layoutEditMode: true,
                    })
            })
        })

        describe('url filter overrides', () => {
            const PROPERTY_OVERRIDE = [{ key: '$browser', value: 'Chrome', type: 'event' }]

            // Dashboard 12 saves `date_from: '-24h'`; dashboard 5 saves no filters.
            const openWithUrlFilters = async (urlFilters: Record<string, any>, dashboardId = 5): Promise<void> => {
                logic.unmount()
                router.actions.push(`/dashboard/${dashboardId}`, {
                    [dashboardUtils.SEARCH_PARAM_FILTERS_KEY]: JSON.stringify(urlFilters),
                })
                logic = dashboardLogic({ id: dashboardId })
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()
            }

            it('drops the url param when the last filter is cleared', async () => {
                await openWithUrlFilters({ properties: PROPERTY_OVERRIDE })
                expect(router.values.searchParams[dashboardUtils.SEARCH_PARAM_FILTERS_KEY]).not.toBeUndefined()

                await expectLogic(logic, () => {
                    logic.actions.setProperties([])
                }).toFinishAllListeners()

                expect(router.values.searchParams[dashboardUtils.SEARCH_PARAM_FILTERS_KEY]).toBeUndefined()
            })

            const historyRefreshCases: [string, Record<string, any>, boolean][] = [
                [
                    'refreshes the tiles when browser history changes the filters',
                    { [dashboardUtils.SEARCH_PARAM_FILTERS_KEY]: JSON.stringify({ date_from: '-7d', date_to: null }) },
                    true,
                ],
                ['leaves the tiles alone when browser history changes nothing', {}, false],
            ]

            it.each(historyRefreshCases)('%s', async (_name, searchParams, expectedRefresh) => {
                await openWithUrlFilters({})
                const getInsightWithRetrySpy = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation(async (_teamId, insight) => insight)

                try {
                    await expectLogic(logic, () => {
                        router.actions.locationChanged({
                            method: 'POP',
                            pathname: '/dashboard/5',
                            search: '',
                            searchParams,
                            hash: '',
                            hashParams: {},
                            url: '/dashboard/5',
                        })
                    }).toFinishAllListeners()

                    if (expectedRefresh) {
                        expect(getInsightWithRetrySpy).toHaveBeenCalled()
                    } else {
                        expect(getInsightWithRetrySpy).not.toHaveBeenCalled()
                    }
                } finally {
                    getInsightWithRetrySpy.mockRestore()
                }
            })

            it('restores filters when browser history changes the URL', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDates('-30d', null)
                }).toFinishAllListeners()

                const searchParams = {
                    [dashboardUtils.SEARCH_PARAM_FILTERS_KEY]: JSON.stringify({ date_from: '-7d', date_to: null }),
                }
                await expectLogic(logic, () => {
                    router.actions.locationChanged({
                        method: 'POP',
                        pathname: '/dashboard/5',
                        search: '',
                        searchParams,
                        hash: '',
                        hashParams: {},
                        url: '/dashboard/5',
                    })
                }).toFinishAllListeners()

                expect(logic.values.currentDashboardSettings.filters).toEqual(
                    expect.objectContaining({ date_from: '-7d', date_to: null })
                )
                expect(logic.values.filtersOverrideForLoad).toEqual(
                    expect.objectContaining({ date_from: '-7d', date_to: null })
                )
            })
        })

        describe('external filter overrides', () => {
            // Dashboards 12 and 18 persist `date_from: '-24h'`, like a dashboard that a scene embeds
            // and drives with its own date picker.
            const openWithExternalFilters = async (dashboardId: number): Promise<void> => {
                logic.unmount()
                router.actions.push(`/dashboard/${dashboardId}`)
                logic = dashboardLogic({ id: dashboardId, placement: DashboardPlacement.Builtin })
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()
            }

            it('lets an external date beat the persisted dashboard filters', async () => {
                await openWithExternalFilters(12)

                await expectLogic(logic, () => {
                    logic.actions.setExternalFilters({ date_from: '-30d', date_to: null })
                }).toFinishAllListeners()

                expect(logic.values.currentDashboardSettings.filters).toEqual(
                    expect.objectContaining({ date_from: '-24h' })
                )
                expect(logic.values.filtersOverrideForLoad).toEqual(
                    expect.objectContaining({ date_from: '-30d', date_to: null })
                )
            })

            it('refreshes the tiles with the external date, not the persisted one', async () => {
                await openWithExternalFilters(18)

                const getInsightWithRetrySpy = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation(async (_teamId, insight) => insight)

                try {
                    await expectLogic(logic, () => {
                        logic.actions.setExternalFilters({ date_from: '-30d', date_to: null })
                    }).toFinishAllListeners()

                    expect(getInsightWithRetrySpy).toHaveBeenCalled()
                    expect(getInsightWithRetrySpy.mock.calls[0][6]).toEqual(
                        expect.objectContaining({ date_from: '-30d', date_to: null })
                    )
                } finally {
                    getInsightWithRetrySpy.mockRestore()
                }
            })
        })

        describe('hasUnsavedLayoutChanges selector', () => {
            it('keeps dashboard data stable while a gesture stages a layout', async () => {
                await expectLogic(logic).toFinishAllListeners()

                const dashboard = logic.values.dashboard
                const firstTile = dashboard!.tiles[0]
                const layouts = logic.values.layouts
                const changedLayouts = {
                    ...layouts,
                    sm: layouts.sm?.map((layout) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 1 } : layout
                    ),
                }

                logic.actions.stageLayouts(changedLayouts)

                expect(logic.values.dashboard).toBe(dashboard)
                expect(logic.values.dashboard!.tiles[0]).toBe(firstTile)
                expect(logic.values.layouts).toEqual(changedLayouts)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(true)

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                }).toFinishAllListeners()

                expect(logic.values.draftLayouts).toBeNull()
                expect(logic.values.hasUnsavedLayoutChanges).toBe(false)
            })

            it('saves staged geometry', async () => {
                await expectLogic(logic).toFinishAllListeners()

                const firstTile = logic.values.dashboard!.tiles[0]
                const layouts = logic.values.layouts
                const changedLayouts = {
                    ...layouts,
                    sm: layouts.sm?.map((layout) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 1 } : layout
                    ),
                }
                logic.actions.stageLayouts(changedLayouts)

                await expectLogic(logic, () => {
                    logic.actions.saveLayoutChanges()
                }).toFinishAllListeners()

                expect(api.update).toHaveBeenCalledWith(
                    `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                    expect.objectContaining({
                        tiles: expect.arrayContaining([
                            expect.objectContaining({
                                id: firstTile.id,
                                layouts: { sm: changedLayouts.sm?.find((layout) => layout.i === String(firstTile.id)) },
                            }),
                        ]),
                    })
                )
            })

            it('keeps staged tile order and height when the scene becomes narrow', async () => {
                await expectLogic(logic).toFinishAllListeners()

                const layouts = logic.values.layouts
                const first = layouts.sm![0]
                const lastY = Math.max(...layouts.sm!.map((layout) => layout.y + layout.h))
                const changedHeight = first.h + 2
                logic.actions.stageLayouts({
                    ...layouts,
                    sm: layouts.sm?.map((layout) =>
                        layout.i === first.i ? { ...layout, y: lastY, h: changedHeight } : layout
                    ),
                })
                logic.actions.updateContainerWidth(500, 1)

                expect(logic.values.layout?.at(-1)?.i).toBe(first.i)
                expect(logic.values.layout?.at(-1)?.h).toBe(changedHeight)
            })

            it('keeps edits made while a layout save is in flight', async () => {
                await expectLogic(logic).toFinishAllListeners()

                const dashboard = logic.values.dashboard!
                const firstTile = dashboard.tiles[0]
                const layouts = logic.values.layouts
                const firstDraft = {
                    ...layouts,
                    sm: layouts.sm?.map((layout) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 1 } : layout
                    ),
                }
                const secondDraft = {
                    ...layouts,
                    sm: layouts.sm?.map((layout) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 2 } : layout
                    ),
                }
                logic.actions.stageLayouts(firstDraft)

                let finishSave: (dashboard: DashboardType) => void = () => {}
                ;(api.update as jest.Mock).mockImplementationOnce(
                    () =>
                        new Promise((resolve) => {
                            finishSave = resolve
                        })
                )
                const save = expectLogic(logic, () => {
                    logic.actions.saveLayoutChanges()
                }).toFinishAllListeners()

                logic.actions.stageLayouts(secondDraft)
                finishSave({
                    ...dashboard,
                    tiles: dashboard.tiles.map((tile) =>
                        tile.id === firstTile.id
                            ? {
                                  ...tile,
                                  layouts: {
                                      sm: firstDraft.sm!.find((layout) => layout.i === String(tile.id))!,
                                  } as DashboardTile['layouts'],
                              }
                            : tile
                    ),
                })
                await save

                expect(logic.values.draftLayouts).toEqual(secondDraft)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
            })

            const moveFirstTile = (): void => {
                const firstTile = logic.values.dashboard!.tiles[0]
                const currentLayouts = logic.values.layouts
                const modifiedLayouts: any = {
                    ...currentLayouts,
                    sm: currentLayouts.sm?.map((layout: any) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                    ),
                }
                logic.actions.updateLayouts(modifiedLayouts)
            }

            it('is false when no tile has been moved', async () => {
                await expectLogic(logic).toFinishAllListeners().toMatchValues({ hasUnsavedLayoutChanges: false })
            })

            it('is false when filters or theme change but layout has not', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDates('-7d', null)
                    logic.actions.setDataColorThemeId(123)
                })
                    .toFinishAllListeners()
                    .toMatchValues({ hasUnsavedLayoutChanges: false })
            })

            it('is true after a layout change', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, moveFirstTile)
                    .toFinishAllListeners()
                    .toMatchValues({ hasUnsavedLayoutChanges: true })
            })

            it('returns to false after discarding changes', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, moveFirstTile)
                    .toFinishAllListeners()
                    .toMatchValues({ hasUnsavedLayoutChanges: true })

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                })
                    .toFinishAllListeners()
                    .toMatchValues({ hasUnsavedLayoutChanges: false })
            })
        })

        describe('changeDashboardGridCompaction action', () => {
            let dialogOpenSpy: jest.SpyInstance

            beforeEach(() => {
                dialogOpenSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            })

            afterEach(() => {
                dialogOpenSpy.mockRestore()
            })

            const moveFirstTile = (): void => {
                const firstTile = logic.values.dashboard!.tiles[0]
                const currentLayouts = logic.values.layouts
                logic.actions.updateLayouts({
                    ...currentLayouts,
                    sm: currentLayouts.sm?.map((layout) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                    ),
                })
            }

            it('changes the movement mode without a prompt when the layout is saved', async () => {
                await expectLogic(logic, () => {
                    logic.actions.changeDashboardGridCompaction(DashboardGridCompaction.Horizontal)
                }).toDispatchActions([
                    logic.actionCreators.setDashboardGridCompaction(DashboardGridCompaction.Horizontal),
                    logic.actionCreators.saveDashboardGridCompaction(DashboardGridCompaction.Horizontal),
                ])

                expect(dialogOpenSpy).not.toHaveBeenCalled()
            })

            it('prompts before changing the movement mode when the layout is unsaved', async () => {
                await expectLogic(logic).toFinishAllListeners()
                await expectLogic(logic, moveFirstTile).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.changeDashboardGridCompaction(DashboardGridCompaction.Horizontal)
                }).toNotHaveDispatchedActions([
                    logic.actionCreators.setDashboardGridCompaction(DashboardGridCompaction.Horizontal),
                    logic.actionCreators.saveDashboardGridCompaction(DashboardGridCompaction.Horizontal),
                ])

                expect(dialogOpenSpy).toHaveBeenCalledWith(
                    expect.objectContaining({
                        title: 'Change tile movement?',
                        description: 'Changing this setting discards your unsaved tile layout changes.',
                    })
                )

                const dialogProps = dialogOpenSpy.mock.calls.at(-1)?.[0]
                dialogProps?.primaryButton?.onClick?.({} as React.MouseEvent<HTMLButtonElement>)

                await expectLogic(logic).toFinishAllListeners().toMatchValues({ hasUnsavedLayoutChanges: false })
            })
        })

        describe('cancelLayoutEdit action', () => {
            // The discard prompt renders a real dialog into its own React root, whose async
            // updates land outside act(); these tests only assert dispatched actions
            let dialogOpenSpy: jest.SpyInstance

            beforeEach(() => {
                dialogOpenSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            })

            afterEach(() => {
                dialogOpenSpy.mockRestore()
            })

            const moveFirstTile = (): void => {
                const firstTile = logic.values.dashboard!.tiles[0]
                const currentLayouts = logic.values.layouts
                const modifiedLayouts: any = {
                    ...currentLayouts,
                    sm: currentLayouts.sm?.map((layout: any) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                    ),
                }
                logic.actions.updateLayouts(modifiedLayouts)
            }

            const setDiscardPromptFlag = (enabled: boolean): void => {
                const flagKey = FEATURE_FLAGS.DASHBOARD_LAYOUT_DISCARD_PROMPT
                featureFlagLogic.actions.setFeatureFlags(enabled ? [flagKey] : [], { [flagKey]: enabled })
            }

            it('exits edit mode immediately when no tile has been moved', async () => {
                setDiscardPromptFlag(true)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.cancelLayoutEdit()
                }).toDispatchActions([
                    logic.actionCreators.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges),
                ])
            })

            it('does not exit edit mode when a tile has been moved and the prompt flag is on', async () => {
                setDiscardPromptFlag(true)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, moveFirstTile).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.cancelLayoutEdit()
                }).toNotHaveDispatchedActions([
                    logic.actionCreators.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges),
                ])
            })

            it('exits edit mode immediately when the prompt flag is off, even with unsaved layout changes', async () => {
                setDiscardPromptFlag(false)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, moveFirstTile).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.cancelLayoutEdit()
                }).toDispatchActions([
                    logic.actionCreators.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges),
                ])
            })
        })

        describe('openAddInsightModal action', () => {
            let confirmSpy: jest.SpyInstance

            beforeEach(() => {
                confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
            })

            afterEach(() => {
                confirmSpy.mockRestore()
            })

            const moveFirstTile = (): void => {
                const firstTile = logic.values.dashboard!.tiles[0]
                const currentLayouts = logic.values.layouts
                const modifiedLayouts: any = {
                    ...currentLayouts,
                    sm: currentLayouts.sm?.map((layout: any) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                    ),
                }
                logic.actions.updateLayouts(modifiedLayouts)
            }

            it('opens the modal without confirming when there are no unsaved layout changes', async () => {
                await expectLogic(logic).toFinishAllListeners()
                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                }).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.openAddInsightModal()
                }).toFinishAllListeners()

                expect(confirmSpy).not.toHaveBeenCalled()
                expect(addInsightToDashboardLogic.values.addInsightToDashboardModalVisible).toBe(true)
            })

            it.each([
                { accepted: true, expectedVisible: true, expectedUnsaved: false },
                { accepted: false, expectedVisible: false, expectedUnsaved: true },
            ])(
                'gates the add-insight modal on the browser confirm (accepted=$accepted)',
                async ({ accepted, expectedVisible, expectedUnsaved }) => {
                    confirmSpy.mockReturnValue(accepted)
                    await expectLogic(logic).toFinishAllListeners()
                    await expectLogic(logic, () => {
                        logic.actions.setDashboardEditing(
                            { filters: true, layout: true },
                            DashboardEventSource.SceneCommonButtons
                        )
                    }).toFinishAllListeners()
                    await expectLogic(logic, moveFirstTile)
                        .toFinishAllListeners()
                        .toMatchValues({ hasUnsavedLayoutChanges: true })

                    await expectLogic(logic, () => {
                        logic.actions.openAddInsightModal()
                    }).toFinishAllListeners()

                    expect(confirmSpy).toHaveBeenCalledTimes(1)
                    expect(addInsightToDashboardLogic.values.addInsightToDashboardModalVisible).toBe(expectedVisible)
                    expect(logic.values.hasUnsavedLayoutChanges).toBe(expectedUnsaved)
                }
            )
        })

        describe('add tile modal with an unsaved layout', () => {
            const moveFirstTile = (): void => {
                const firstTile = logic.values.dashboard!.tiles[0]
                logic.actions.updateLayouts({
                    ...logic.values.layouts,
                    sm: logic.values.layouts.sm?.map((layout) =>
                        layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 1 } : layout
                    ),
                })
            }

            it.each([
                ['image', 'showImageTileModal', () => logic.actions.openImageTileModal()],
                ['button', 'showButtonTileModal', () => logic.actions.openButtonTileModal()],
                ['text', 'showTextTileModal', () => logic.actions.openTextTileModal()],
            ] as const)('keeps draft layout after cancelling %s', async (_type, visibleKey, open) => {
                const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(false)
                try {
                    await expectLogic(logic).toFinishAllListeners()
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                    moveFirstTile()
                    const draftLayouts = logic.values.layouts

                    open()
                    expect(logic.values[visibleKey]).toBe(true)
                    logic.actions.closeTileModal()

                    expect(logic.values[visibleKey]).toBe(false)
                    expect(logic.values.dashboardEditing?.layout).toBe(true)
                    expect(logic.values.layouts).toEqual(draftLayouts)
                    expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
                    expect(confirmSpy).not.toHaveBeenCalled()
                } finally {
                    confirmSpy.mockRestore()
                }
            })

            it('keeps the draft layout when adding an image', async () => {
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
                moveFirstTile()
                const draftLayout = logic.values.dashboard!.tiles[0].layouts
                const savedDashboard = {
                    ...logic.values.dashboard!,
                    tiles: [
                        ...dashboards[5].tiles,
                        {
                            id: 999,
                            text: { body: '![Example](https://example.com/example.png)' },
                            layouts: {},
                            color: null,
                        } as DashboardTile,
                    ],
                }

                dashboardsModel.actions.updateDashboardSuccess(savedDashboard)

                expect(logic.values.dashboard!.tiles[0].layouts).toEqual(draftLayout)
                expect(logic.values.dashboard!.tiles).toHaveLength(savedDashboard.tiles.length)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
                expect(logic.values.dashboardEditing?.layout).toBe(true)
            })

            it('keeps a layout draft unsaved when a client-built widget update echoes it', async () => {
                await expectLogic(logic).toFinishAllListeners()
                moveFirstTile()
                const draftTile = logic.values.dashboard!.tiles[0]
                const savedLayouts = logic.values.savedTilePlacements[draftTile.id]?.layouts
                const addedTile = { ...WIDGET_TILE, id: 999 }
                const updatedDashboard = {
                    ...logic.values.dashboard!,
                    tiles: [...logic.values.dashboard!.tiles, addedTile],
                }

                dashboardsModel.actions.updateDashboardSuccess(updatedDashboard)

                expect(logic.values.dashboard!.tiles[0].layouts).toEqual(draftTile.layouts)
                expect(logic.values.savedTilePlacements[draftTile.id]?.layouts).toEqual(savedLayouts)
                expect(logic.values.savedTilePlacements[addedTile.id]?.layouts).toEqual(addedTile.layouts)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
            })

            it('uses the server layout for tiles without draft changes', async () => {
                await expectLogic(logic).toFinishAllListeners()
                const firstTile = logic.values.dashboard!.tiles[1]
                const currentLayout = logic.values.layouts.sm!.find((layout) => layout.i === String(firstTile.id))!
                const serverLayouts = {
                    sm: { ...currentLayout, x: currentLayout.x + 2 },
                } as DashboardTile['layouts']
                const savedDashboard = {
                    ...logic.values.dashboard!,
                    tiles: logic.values.dashboard!.tiles.map((tile) =>
                        tile.id === firstTile.id ? { ...tile, layouts: serverLayouts } : tile
                    ),
                }

                await expectLogic(logic, () =>
                    dashboardsModel.actions.updateDashboardSuccess(savedDashboard, { layoutsPersisted: true })
                )
                    .toDispatchActions(['applyDashboardUpdate'])
                    .toFinishAllListeners()

                expect(logic.values.dashboard!.tiles[1].layouts).toEqual(serverLayouts)
                expect(logic.values.savedTilePlacements[firstTile.id]?.layouts).toEqual(serverLayouts)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(false)
            })

            it('preserves only the changed tile draft when another tile receives a server layout update', async () => {
                await expectLogic(logic).toFinishAllListeners()
                moveFirstTile()
                const draftTile = logic.values.dashboard!.tiles[0]
                const unchangedTile = logic.values.dashboard!.tiles[1]
                const currentLayout = logic.values.layouts.sm!.find((layout) => layout.i === String(unchangedTile.id))!
                const serverLayouts = {
                    sm: { ...currentLayout, x: currentLayout.x + 2 },
                } as DashboardTile['layouts']
                const savedDashboard = {
                    ...logic.values.dashboard!,
                    tiles: logic.values.dashboard!.tiles.map((tile) =>
                        tile.id === unchangedTile.id
                            ? { ...tile, layouts: serverLayouts }
                            : tile.id === draftTile.id
                              ? dashboards[5].tiles.find((savedTile) => savedTile.id === draftTile.id)!
                              : tile
                    ),
                }

                await expectLogic(logic, () =>
                    dashboardsModel.actions.updateDashboardSuccess(savedDashboard, { layoutsPersisted: true })
                )
                    .toDispatchActions(['applyDashboardUpdate'])
                    .toFinishAllListeners()

                expect(logic.values.dashboard!.tiles[0].layouts).toEqual(draftTile.layouts)
                expect(logic.values.dashboard!.tiles[1].layouts).toEqual(serverLayouts)
                expect(logic.values.savedTilePlacements[unchangedTile.id]?.layouts).toEqual(serverLayouts)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
            })

            it.each([{ layoutsPersisted: false }, { layoutsPersisted: true }])(
                'keeps an unsaved group move when an update echoes the saved group (layouts persisted: $layoutsPersisted)',
                async ({ layoutsPersisted }) => {
                    await expectLogic(logic).toFinishAllListeners()
                    const draftTile = logic.values.dashboard!.tiles[0]
                    logic.actions.setTileProperty(draftTile.id, { group_key: 'plans' })
                    const echo = {
                        ...logic.values.dashboard!,
                        tiles: logic.values.dashboard!.tiles.map((tile) =>
                            tile.id === draftTile.id ? { ...tile, group_key: null } : tile
                        ),
                    }

                    dashboardsModel.actions.updateDashboardSuccess(echo, { layoutsPersisted })

                    expect(logic.values.dashboard!.tiles[0].group_key).toBe('plans')
                    expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
                }
            )

            it('uses the returned saved layout as the snapshot when the same tile has a draft', async () => {
                await expectLogic(logic).toFinishAllListeners()
                moveFirstTile()
                const draftTile = logic.values.dashboard!.tiles[0]
                const savedLayouts = {
                    sm: { ...draftTile.layouts!.sm!, x: draftTile.layouts!.sm!.x + 1 },
                } as DashboardTile['layouts']
                const savedDashboard = {
                    ...logic.values.dashboard!,
                    tiles: logic.values.dashboard!.tiles.map((tile) =>
                        tile.id === draftTile.id ? { ...tile, layouts: savedLayouts } : tile
                    ),
                }

                await expectLogic(logic, () =>
                    dashboardsModel.actions.updateDashboardSuccess(savedDashboard, { layoutsPersisted: true })
                )
                    .toDispatchActions(['applyDashboardUpdate'])
                    .toFinishAllListeners()

                expect(logic.values.dashboard!.tiles[0].layouts).toEqual(draftTile.layouts)
                expect(logic.values.savedTilePlacements[draftTile.id]?.layouts).toEqual(savedLayouts)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
            })

            it('clears the layout draft when the server persists the same geometry', async () => {
                await expectLogic(logic).toFinishAllListeners()
                moveFirstTile()
                const draftTile = logic.values.dashboard!.tiles[0]
                const savedDashboard = { ...logic.values.dashboard! }

                await expectLogic(logic, () =>
                    dashboardsModel.actions.updateDashboardSuccess(savedDashboard, { layoutsPersisted: true })
                )
                    .toDispatchActions(['applyDashboardUpdate'])
                    .toFinishAllListeners()

                expect(logic.values.savedTilePlacements[draftTile.id]?.layouts).toEqual(draftTile.layouts)
                expect(logic.values.hasUnsavedLayoutChanges).toBe(false)
            })

            it('still asks before navigating away from unsaved layout changes', async () => {
                const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(false)
                try {
                    router.actions.push(urls.dashboard(5))
                    await expectLogic(logic).toFinishAllListeners()
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: true },
                        DashboardEventSource.SceneCommonButtons
                    )
                    moveFirstTile()

                    router.actions.push(urls.dashboard(6))

                    expect(confirmSpy).toHaveBeenCalledWith(
                        'Leave dashboard?\nChanges you made to the layout will be discarded.'
                    )
                    expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
                } finally {
                    confirmSpy.mockRestore()
                }
            })
        })

        describe('colors modal cancel', () => {
            beforeEach(() => {
                dashboardInsightColorsModalLogic.mount()
            })

            it('discards color edits and exits edit mode when the modal was opened from view mode', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    dashboardInsightColorsModalLogic.actions.showInsightColorsModal(5)
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: false },
                        DashboardEventSource.DashboardInsightColorsModal
                    )
                    logic.actions.setBreakdownColorConfig({
                        breakdownValue: 'x',
                        breakdownType: 'event',
                        colorToken: 'preset-1',
                    })
                    logic.actions.setDataColorThemeId(123)
                }).toFinishAllListeners()

                expect(logic.values.hasUnsavedColorChanges).toBe(true)

                await expectLogic(logic, () => {
                    dashboardInsightColorsModalLogic.actions.cancelColorChanges()
                }).toFinishAllListeners()

                expect(dashboardInsightColorsModalLogic.values.isOpen).toBe(false)
                expect(logic.values.dashboardMode).toBeNull()
                expect(logic.values.hasUnsavedColorChanges).toBe(false)
                expect(logic.values.dataColorThemeId).toBe(logic.values.dashboard?.data_color_theme_id ?? null)
            })

            it('reverts only the modal color edits and stays in edit mode when edit mode predates the modal', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardEditing(
                        { filters: true, layout: false },
                        DashboardEventSource.DashboardFilters
                    )
                    logic.actions.setDates('-7d', null)
                    logic.actions.setBreakdownColorConfig({
                        breakdownValue: 'x',
                        breakdownType: 'event',
                        colorToken: 'preset-1',
                    })
                }).toFinishAllListeners()

                await expectLogic(logic, () => {
                    dashboardInsightColorsModalLogic.actions.showInsightColorsModal(5)
                    logic.actions.setBreakdownColorConfig({
                        breakdownValue: 'y',
                        breakdownType: 'event',
                        colorToken: 'preset-2',
                    })
                }).toFinishAllListeners()

                await expectLogic(logic, () => {
                    dashboardInsightColorsModalLogic.actions.cancelColorChanges()
                }).toFinishAllListeners()

                expect(dashboardInsightColorsModalLogic.values.isOpen).toBe(false)
                expect(logic.values.dashboardEditing).toEqual({ filters: true, layout: false })
                expect(logic.values.effectiveEditBarFilters.date_from).toBe('-7d')
                expect(logic.values.temporaryBreakdownColors).toEqual([
                    expect.objectContaining({ breakdownValue: 'x', colorToken: 'preset-1' }),
                ])
            })
        })
    })

    it('captures a dashboard view after the logic unmounts during the debounce', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        jest.useFakeTimers()
        try {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            logic.actions.reportDashboardViewedEvent(dashboards[5], null)
            expect(capture.mock.calls.filter(([event]) => event === 'viewed dashboard')).toHaveLength(0)
            logic.unmount()
            expect(logic.isMounted()).toBe(false)
            await jest.advanceTimersByTimeAsync(499)
            expect(capture.mock.calls.filter(([event]) => event === 'viewed dashboard')).toHaveLength(0)
            await jest.advanceTimersByTimeAsync(1)
            expect(capture.mock.calls.filter(([event]) => event === 'viewed dashboard')).toEqual([
                ['viewed dashboard', expect.objectContaining({ dashboard_id: 5, source: 'web' })],
            ])
        } finally {
            jest.useRealTimers()
            capture.mockRestore()
        }
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
            const startingDashboard = dashboards[9]

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
                `api/projects/${MOCK_TEAM_ID}/dashboards/${9}/move_tile`,
                expect.objectContaining({ tile: sourceTile, to_dashboard: 8 })
            )
        })

        it('records a copied insight tile on the source tile, so the copy menu treats the destination as taken', async () => {
            // insight 800 starts on dashboard 9 and 10
            await expectLogic(logic).toFinishAllListeners()
            const sourceTile = logic.values.insightTiles[0]
            jest.spyOn(api, 'create').mockResolvedValueOnce({ id: 8, tiles: [{ id: 555, insight: { id: 800 } }] })

            await expectLogic(logic, () => {
                logic.actions.copyToDashboard(sourceTile, 9, 8, 'targetDashboard')
            }).toFinishAllListeners()

            const insightTiles = logic.values.insightTiles[0].insight!.dashboard_tiles
            expect(insightTiles).toContainEqual({ id: 555, dashboard_id: 8 })
            expect(liveDashboardIds(insightTiles)).toEqual([9, 10, 8])
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
                .toDispatchActions(['loadDashboardSuccess'])
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

        it.each([
            {
                trigger: 'a request succeeds again',
                recover: () => apiStatusLogic.actions.setInternetConnectionIssue(false),
            },
            {
                trigger: 'the browser goes back online',
                recover: () => window.dispatchEvent(new Event('online')),
            },
        ])('keeps the error state during a retry and retries when $trigger', async ({ recover }) => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.dashboardFailedToLoad).toBe(true)

            await expectLogic(logic, recover)
                .toDispatchActions(['retryDashboardLoad', 'loadDashboard'])
                .toMatchValues({ dashboardFailedToLoad: true, dashboardLoading: true })
                .toDispatchActions(['loadDashboardFailure'])
                .toMatchValues({ dashboardFailedToLoad: true, dashboardLoading: false })

            await expectLogic(logic, () => {
                apiStatusLogic.actions.setInternetConnectionIssue(true)
            }).toNotHaveDispatchedActions(['retryDashboardLoad'])
        })

        it.each(
            ['request', 'online'].flatMap((trigger) => [true, false].map((initialLoad) => ({ trigger, initialLoad })))
        )(
            'retries once when $trigger signals recovery during a failed load (initial=$initialLoad)',
            async ({ trigger, initialLoad }) => {
                if (!initialLoad) {
                    await expectLogic(logic).toFinishAllListeners()
                }
                apiStatusLogic.actions.setInternetConnectionIssue(true)

                await expectLogic(logic, () => {
                    if (!initialLoad) {
                        logic.actions.loadDashboard({ action: DashboardLoadAction.Update })
                    }
                    if (trigger === 'online') {
                        window.dispatchEvent(new Event('online'))
                        apiStatusLogic.actions.setInternetConnectionIssue(true)
                    } else {
                        apiStatusLogic.actions.setInternetConnectionIssue(false)
                    }
                })
                    .toDispatchActions([
                        'loadDashboardFailure',
                        'retryDashboardLoad',
                        'loadDashboard',
                        'loadDashboardFailure',
                    ])
                    .toFinishAllListeners()
                    .toNotHaveDispatchedActions(['retryDashboardLoad'])
            }
        )

        it.each([
            { id: 14, accessDenied: false },
            { id: 15, accessDenied: true },
            { id: 16, accessDenied: false },
        ])('classifies dashboard HTTP failures for dashboard $id', async ({ id, accessDenied }) => {
            logic = dashboardLogic({ id })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.accessDeniedToDashboard).toBe(accessDenied)
            expect(logic.values.dashboardFailedToLoad).toBe(true)
            expect(logic.values.error404).toBe(false)
        })

        it('treats an invalid successful response as a load failure', async () => {
            jest.spyOn(api, 'getResponse').mockResolvedValueOnce(
                new Response('<html>Bad gateway</html>', { status: 200 })
            )
            logic = dashboardLogic({ id: 17 })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dashboardFailedToLoad).toBe(true)
            expect(logic.values.error404).toBe(false)
        })

        describe('when the dashboard GET returns 404', () => {
            beforeEach(() => {
                logic = dashboardLogic({ id: 13 })
                logic.mount()
            })

            // The NotFound scene is gated on error404, so the loader must set it once the fetch
            // settles as a 404 — and must NOT set it before the request has been made.
            it('sets error404 after a settled 404 and not before', async () => {
                expect(logic.values.error404).toBe(false)

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.dashboard).toBeNull()
                expect(logic.values.dashboardFailedToLoad).toBe(false)
                expect(logic.values.error404).toBe(true)
            })

            // Logging in lands a person on their configured home. When that home is this dashboard and
            // it was deleted, this screen is all they ever see, so the stale setting must go.
            it('clears a configured homepage that points at this dashboard', async () => {
                const scene = sceneLogic({ scenes: {} })
                scene.mount()
                scene.actions.setHomepage({
                    id: 'homepage-dashboard',
                    pathname: urls.dashboard(13),
                    search: '',
                    hash: '',
                    title: 'Home dashboard',
                    iconType: 'dashboard',
                    sceneId: Scene.Dashboard,
                    sceneParams: { params: {}, searchParams: {}, hashParams: {} },
                })
                router.actions.push(urls.dashboard(13))

                await expectLogic(logic).toFinishAllListeners()
                await expectLogic(scene).toFinishAllListeners()

                expect(scene.values.homepage).toBeNull()
                scene.unmount()
            })
        })
    })

    describe('tile streaming failure classification', () => {
        let lemonToastErrorSpy: jest.SpiedFunction<typeof lemonToast.error>

        beforeEach(silenceKeaLoadersErrors)
        afterEach(resumeKeaLoadersErrors)

        beforeEach(() => {
            lemonToastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
            logic = dashboardLogic({ id: 5 })
            logic.mount()
        })

        afterEach(() => {
            lemonToastErrorSpy.mockRestore()
        })

        // A genuine 404 from the stream's initial response is the only signal that flips the scene to
        // "Dashboard not found". A stream error whose message merely mentions 404 (e.g. a tile query that
        // failed upstream) carries no status and must stay a toast — string-matching '404' used to turn
        // these blips into a hard NotFound on valid, loaded dashboards.
        it('only marks NotFound on a real 404 status, not a message that mentions 404', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({ message: 'Query failed with code 404 upstream' }, true)
            }).toFinishAllListeners()
            expect(logic.values.error404).toBe(false)
            expect(logic.values.dashboardFailedToLoad).toBe(false)
            expect(lemonToastErrorSpy).toHaveBeenCalled()

            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({ message: 'gone', status: 404 })
            }).toFinishAllListeners()
            expect(logic.values.error404).toBe(true)
        })

        it('makes a definitive 404 authoritative over an earlier stream failure and stale dashboard', async () => {
            logic.actions.tileStreamingFailure({ message: 'network dropped mid-connect' })
            expect(logic.values.dashboardFailedToLoad).toBe(true)

            logic.actions.loadDashboardMetadataSuccess(dashboardResult(5, []))
            expect(logic.values.dashboard).not.toBeNull()

            logic.actions.setDashboardStreamFailed()
            logic.actions.tileStreamingFailure({ message: 'gone', status: 404 })

            expect(logic.values.error404).toBe(true)
            expect(logic.values.dashboardFailedToLoad).toBe(false)
            expect(logic.values.accessDeniedToDashboard).toBe(false)
            expect(logic.values.dashboard).toBeNull()
        })

        it('fails a completed stream without metadata and disposes it on unmount', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.dashboardNotFound()

            const disposeStream = jest.fn()
            jest.spyOn(api.dashboards, 'streamTiles').mockImplementation(
                async (_id, _params, _onMessage, onComplete) => {
                    onComplete()
                    return disposeStream
                }
            )

            await expectLogic(logic, () => {
                logic.actions.loadDashboardStreaming({ action: DashboardLoadAction.InitialLoad })
            }).toFinishAllListeners()

            expect(logic.values.dashboardFailedToLoad).toBe(true)
            expect(logic.values.error404).toBe(false)

            logic.unmount()
            expect(disposeStream).toHaveBeenCalledTimes(1)
        })

        it('clears NotFound when a streaming retry starts or delivers metadata', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({ message: 'gone', status: 404 })
            }).toFinishAllListeners()
            expect(logic.values.error404).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.loadDashboardStreaming({ action: DashboardLoadAction.InitialLoad })
            }).toFinishAllListeners()
            expect(logic.values.error404).toBe(false)

            logic.actions.tileStreamingFailure({ message: 'gone', status: 404 })
            expect(logic.values.error404).toBe(true)

            logic.actions.loadDashboardMetadataSuccess(dashboardResult(5, []))
            expect(logic.values.error404).toBe(false)
        })

        it('clears access denied when a streaming retry starts or delivers metadata', async () => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.tileStreamingFailure({
                message: 'forbidden',
                status: 403,
                code: 'permission_denied',
            })
            expect(logic.values.accessDeniedToDashboard).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.loadDashboardStreaming({ action: DashboardLoadAction.InitialLoad })
            }).toFinishAllListeners()
            expect(logic.values.accessDeniedToDashboard).toBe(false)

            logic.actions.tileStreamingFailure({
                message: 'forbidden',
                status: 403,
                code: 'permission_denied',
            })
            expect(logic.values.accessDeniedToDashboard).toBe(true)

            logic.actions.loadDashboardMetadataSuccess(dashboardResult(5, []))
            expect(logic.values.accessDeniedToDashboard).toBe(false)
        })

        it('routes a 403 status to access denied and other errors to a toast', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({
                    message: 'forbidden',
                    status: 403,
                    code: 'permission_denied',
                })
            }).toFinishAllListeners()
            expect(logic.values.accessDeniedToDashboard).toBe(true)
            expect(logic.values.error404).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({ message: 'HTTP 500: something broke', status: 500 })
            }).toFinishAllListeners()
            expect(lemonToastErrorSpy).toHaveBeenCalledWith(expect.stringContaining('something broke'))
            expect(logic.values.dashboardFailedToLoad).toBe(true)
        })

        it('marks the load failed (not NotFound) when a transient error leaves no dashboard', async () => {
            expect(logic.values.dashboard).toBeNull()

            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({ message: 'network dropped mid-connect' })
            }).toDispatchActions(['setDashboardStreamFailed'])

            expect(logic.values.dashboardFailedToLoad).toBe(true)
            expect(logic.values.error404).toBe(false)
        })

        // fetchEventSource auto-retries transient failures, so the stream can recover on its own:
        // metadata arriving after a failure must clear the load-error state, not leave it latched
        // over a fully loaded dashboard.
        it('clears the failed state when a stream retry delivers metadata', async () => {
            await expectLogic(logic, () => {
                logic.actions.tileStreamingFailure({ message: 'network dropped mid-connect' })
            }).toDispatchActions(['setDashboardStreamFailed'])
            expect(logic.values.dashboardFailedToLoad).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.loadDashboardMetadataSuccess(dashboardResult(5, []))
            }).toFinishAllListeners()

            expect(logic.values.dashboardFailedToLoad).toBe(false)
            expect(logic.values.dashboard).not.toBeNull()
        })

        it.each(['request', 'online'].flatMap((trigger) => [false, true].map((metadata) => ({ trigger, metadata }))))(
            'keeps an auto-retrying stream on $trigger recovery but replaces an ended one (metadata=$metadata)',
            async ({ trigger, metadata }) => {
                const globals = globalThis as { EventSource?: unknown }
                const originalEventSource = globals.EventSource
                globals.EventSource = class {}
                try {
                    await expectLogic(logic).toFinishAllListeners()
                    logic.actions.dashboardNotFound()
                    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSE_DASHBOARDS], {
                        [FEATURE_FLAGS.SSE_DASHBOARDS]: true,
                    })
                    const disposeStream = jest.fn()
                    const streamTilesSpy = jest.spyOn(api.dashboards, 'streamTiles').mockResolvedValue(disposeStream)
                    await expectLogic(logic, () => {
                        logic.actions.loadDashboardStreaming({ action: DashboardLoadAction.InitialLoad })
                    }).toFinishAllListeners()
                    const recover = (): void => {
                        if (trigger === 'online') {
                            window.dispatchEvent(new Event('online'))
                        } else {
                            apiStatusLogic.actions.setInternetConnectionIssue(false)
                        }
                    }
                    if (metadata) {
                        streamTilesSpy.mock.calls[0][2]({ type: 'metadata', dashboard: dashboardResult(5, []) })
                        streamTilesSpy.mock.calls[0][2]({ type: 'tile', tile: TEXT_TILE })
                        streamTilesSpy.mock.calls[0][2]({ type: 'tile', tile: { ...TEXT_TILE, id: 99 } })
                    }
                    const onError = streamTilesSpy.mock.calls[0][4]
                    await expectLogic(logic, () =>
                        onError(new TypeError('Failed to fetch'), true)
                    ).toFinishAllListeners()
                    expect(logic.values.dashboardFailedToLoad).toBe(!metadata)

                    await expectLogic(logic, recover).toFinishAllListeners()
                    expect(streamTilesSpy).toHaveBeenCalledTimes(1)
                    expect(disposeStream).not.toHaveBeenCalled()

                    await expectLogic(logic, () =>
                        onError(new SyntaxError('Unreadable dashboard message'))
                    ).toFinishAllListeners()
                    expect(logic.values.dashboardFailedToLoad).toBe(true)
                    await expectLogic(logic, recover).toFinishAllListeners()
                    expect(streamTilesSpy).toHaveBeenCalledTimes(2)
                    expect(disposeStream).toHaveBeenCalledTimes(1)
                    if (metadata) {
                        expect(logic.values.tiles?.map((tile) => tile.id)).toEqual([TEXT_TILE.id, 99])
                    }

                    await expectLogic(logic, () => {
                        streamTilesSpy.mock.calls[1][2]({ type: 'metadata', dashboard: dashboardResult(5, []) })
                        streamTilesSpy.mock.calls[1][2]({ type: 'tile', tile: TEXT_TILE })
                    }).toFinishAllListeners()
                    if (metadata) {
                        expect(logic.values.tiles?.map((tile) => tile.id)).toEqual([TEXT_TILE.id, 99])
                        expect(logic.values.dashboardFailedToLoad).toBe(true)
                    }

                    await expectLogic(logic, () => {
                        streamTilesSpy.mock.calls[1][2]({ type: 'tile', tile: { ...TEXT_TILE, id: 6 } })
                        streamTilesSpy.mock.calls[1][3]()
                    }).toFinishAllListeners()
                    expect(logic.values.dashboard?.id).toBe(5)
                    expect(logic.values.tiles?.map((tile) => tile.id)).toEqual([TEXT_TILE.id, 6])
                    expect(logic.values.dashboardFailedToLoad).toBe(false)
                } finally {
                    globals.EventSource = originalEventSource
                }
            }
        )

        it('keeps the stream that recovered while a connection retry waited', async () => {
            const globals = globalThis as { EventSource?: unknown }
            const originalEventSource = globals.EventSource
            globals.EventSource = class {}
            try {
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.dashboardNotFound()
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSE_DASHBOARDS], {
                    [FEATURE_FLAGS.SSE_DASHBOARDS]: true,
                })
                logic.actions.tileStreamingFailure({ message: 'network dropped mid-connect' })
                expect(logic.values.dashboardFailedToLoad).toBe(true)
                const streamTilesSpy = jest.spyOn(api.dashboards, 'streamTiles').mockResolvedValue(jest.fn())

                await expectLogic(logic, () => {
                    apiStatusLogic.actions.setInternetConnectionIssue(false)
                    logic.actions.loadDashboardMetadataSuccess(dashboardResult(5, []))
                })
                    .toDispatchActions([
                        'retryDashboardLoad',
                        'loadDashboardStreaming',
                        'loadDashboardStreamingSuccess',
                    ])
                    .toFinishAllListeners()

                expect(streamTilesSpy).not.toHaveBeenCalled()
                expect(logic.values.dashboard).not.toBeNull()
                expect(logic.values.dashboardFailedToLoad).toBe(false)
            } finally {
                globals.EventSource = originalEventSource
            }
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
                        dashboard: expect.objectContaining(dashboards[5]),
                        tiles: truth((tiles) => tiles.length === 3),
                        insightTiles: truth((insightTiles) => insightTiles.length === 2),
                        textTiles: truth((textTiles) => textTiles.length === 1),
                        dashboardFailedToLoad: false,
                    })
            })
        })

        describe('last refreshed display', () => {
            it.each([
                {
                    scenario: 'all insight tiles share the same older last_refresh',
                    staleIso: '2026-01-15T12:00:00.000Z',
                    mode: 'all-stale' as const,
                },
                {
                    scenario: 'tiles have mixed last_refresh so the banner follows the stalest',
                    staleIso: '2026-01-15T10:00:00.000Z',
                    mode: 'mixed' as const,
                },
            ])('effectiveLastRefresh stays at the stalest tile — $scenario', async ({ staleIso, mode }) => {
                await expectLogic(logic).toFinishAllListeners()

                const loaded = logic.values.dashboard!
                if (mode === 'all-stale') {
                    expect(loaded.tiles?.length).toBeGreaterThan(0)
                    for (const tile of loaded.tiles) {
                        const insight = tile.insight
                        if (!insight) {
                            continue
                        }

                        await expectLogic(logic, () => {
                            dashboardsModel.actions.updateDashboardInsight(
                                { ...insight, last_refresh: staleIso, query: insight.query ?? null },
                                undefined,
                                5
                            )
                        }).toFinishAllListeners()
                    }
                } else {
                    const insightTiles = loaded.tiles.filter((t) => !!t.insight)
                    expect(insightTiles.length).toBeGreaterThanOrEqual(2)
                    const freshIso = now().toISOString()
                    await expectLogic(logic, () => {
                        dashboardsModel.actions.updateDashboardInsight(
                            {
                                ...insightTiles[0].insight!,
                                last_refresh: staleIso,
                                query: insightTiles[0].insight!.query ?? null,
                            },
                            undefined,
                            5
                        )
                    }).toFinishAllListeners()
                    await expectLogic(logic, () => {
                        dashboardsModel.actions.updateDashboardInsight(
                            {
                                ...insightTiles[1].insight!,
                                last_refresh: freshIso,
                                query: insightTiles[1].insight!.query ?? null,
                            },
                            undefined,
                            5
                        )
                    }).toFinishAllListeners()
                }

                await expectLogic(logic, () => {
                    logic.actions.updateDashboardLastRefresh(now())
                }).toFinishAllListeners()

                expect(logic.values.oldestRefreshed?.toISOString()).toEqual(dayjs(staleIso).toISOString())
                expect(logic.values.effectiveLastRefresh?.toISOString()).toEqual(dayjs(staleIso).toISOString())
                expect(logic.values.blockRefresh).toBe(false)
            })

            it('persisting the last refresh keeps refreshed results instead of an earlier snapshot', async () => {
                await expectLogic(logic).toFinishAllListeners()

                const snapshot = logic.values.dashboard!
                dashboardsModel.actions.updateDashboardSuccess(snapshot)

                const insight = snapshot.tiles.find((tile) => !!tile.insight)!.insight!
                const freshResult = [{ count: 42 }]

                await expectLogic(logic, () => {
                    dashboardsModel.actions.updateDashboardInsight(
                        { ...insight, result: freshResult, query: insight.query ?? null },
                        undefined,
                        5
                    )
                }).toFinishAllListeners()

                await expectLogic(dashboardsModel, () => {
                    logic.actions.updateDashboardLastRefresh(now())
                }).toDispatchActions(['updateDashboard', 'updateDashboardSuccess'])

                const refreshedTile = logic.values.tiles.find((tile) => tile.insight?.short_id === insight.short_id)
                expect(refreshedTile?.insight?.result).toEqual(freshResult)
            })
        })

        describe('insight refresh', () => {
            it('allows another manual dashboard refresh after five minutes', async () => {
                await expectLogic(logic).toFinishAllListeners()
                for (const tile of logic.values.dashboard!.tiles) {
                    const insight = tile.insight
                    if (!insight) {
                        continue
                    }
                    await expectLogic(logic, () => {
                        dashboardsModel.actions.updateDashboardInsight(
                            { ...insight, last_refresh: now().toISOString(), query: insight.query ?? null },
                            undefined,
                            5
                        )
                    }).toFinishAllListeners()
                }

                jest.useFakeTimers()
                try {
                    const recentRefresh = now().subtract(4, 'minutes')
                    logic.actions.updateDashboardLastRefresh(recentRefresh)
                    expect(logic.values.blockRefresh).toBe(true)

                    await jest.advanceTimersByTimeAsync(60_100)
                    expect(logic.values.blockRefresh).toBe(false)

                    const lastRefresh = now().subtract(6, 'minutes')
                    logic.actions.updateDashboardLastRefresh(lastRefresh)
                    expect(logic.values.nextAllowedDashboardRefresh?.isSame(lastRefresh.add(5, 'minutes'))).toBe(true)
                    expect(logic.values.blockRefresh).toBe(false)
                } finally {
                    jest.useRealTimers()
                }
            })

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
                        // Y is captured up front when the batch is enrolled, so it stays fixed
                        // for the whole cycle rather than tracking the still-populating map.
                        refreshTilesTotal: 2,
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

            it.each([
                ['rate_limited', 'Queries are a little too busy right now.', 429],
                ['table_access_denied', "You don't have access to table `events`.", 400],
                [null, "'NoneType' object has no attribute 'get'", null],
            ])(
                'keeps tile data and marks the tile errored when a refresh terminates in a %s rejection stub',
                async (errorCode, errorMessage, expectedStatus) => {
                    const dashboard = dashboards[5]
                    const insight1 = dashboard.tiles[0].insight!
                    const insight2 = dashboard.tiles[1].insight!
                    const resultsBeforeRefresh = logic.values.insightTiles.map((t) => t.insight!.result)
                    expect(resultsBeforeRefresh.every((r) => r != null)).toBe(true)

                    // What getInsightWithRetry resolves to when the app-level concurrency limiter (or a
                    // server-side calculation error) rejects every attempt: an insight-shaped payload with
                    // no result and an errored query_status
                    const getInsightWithRetrySpy = jest
                        .spyOn(dashboardUtils, 'getInsightWithRetry')
                        .mockImplementation(async (_teamId, insight) => ({
                            ...insight,
                            result: null,
                            query_status: {
                                id: 'rejected-query',
                                team_id: 2,
                                query_async: true,
                                complete: false,
                                error: true,
                                error_code: errorCode,
                                error_message: errorMessage,
                            },
                        }))

                    try {
                        await expectLogic(logic, () => {
                            logic.actions.triggerDashboardRefresh()
                        }).toFinishAllListeners()

                        // The stub must not be committed as a successful refresh: tiles keep their data
                        expect(logic.values.insightTiles.map((t) => t.insight!.result)).toEqual(resultsBeforeRefresh)
                        // and surface an error state instead of rendering the null result as an empty insight
                        for (const shortId of [insight1.short_id, insight2.short_id]) {
                            const status = logic.values.refreshStatus[shortId]
                            expect(status?.errored).toBe(true)
                            expect(status?.error).toEqual(
                                expectedStatus === null
                                    ? undefined
                                    : expect.objectContaining({
                                          status: expectedStatus,
                                          detail: errorMessage,
                                          code: errorCode,
                                      })
                            )
                        }
                    } finally {
                        getInsightWithRetrySpy.mockRestore()
                    }
                }
            )

            it('pins the "X out of Y" denominator when a tile aborts mid-cycle and keeps siblings tracked', async () => {
                const dashboard = dashboards[5]
                const insight1 = dashboard.tiles[0].insight!
                const insight2 = dashboard.tiles[1].insight!

                // Hold both insight fetches in flight so we can observe a mid-cycle abort while the batch is live.
                const gates: Record<string, { barrier: Promise<void>; release: () => void }> = {}
                for (const shortId of [insight1.short_id, insight2.short_id]) {
                    let release!: () => void
                    const barrier = new Promise<void>((resolve): void => {
                        release = resolve
                    })
                    gates[shortId] = { barrier, release }
                }

                const realGetInsightWithRetry =
                    jest.requireActual<typeof dashboardUtils>('./dashboardUtils').getInsightWithRetry

                const getInsightWithRetrySpy = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation(
                        async (
                            ...args: Parameters<typeof realGetInsightWithRetry>
                        ): ReturnType<typeof realGetInsightWithRetry> => {
                            await gates[args[1].short_id].barrier
                            return realGetInsightWithRetry(...args)
                        }
                    )
                const cancelQuerySpy = jest.spyOn(api.insights, 'cancelQuery').mockResolvedValue(undefined as any)

                const poll = async (cond: () => boolean, message: string): Promise<void> => {
                    const deadline = Date.now() + 5000
                    while (!cond()) {
                        if (Date.now() > deadline) {
                            throw new Error(message)
                        }
                        await new Promise((r) => setTimeout(r, 0))
                    }
                }

                try {
                    // forceRefresh: true so both tiles enter the refresh loop
                    const refreshDone = expectLogic(logic, () => {
                        logic.actions.triggerDashboardRefresh()
                    }).toFinishAllListeners()

                    // Both tiles enrolled up front and in flight: Y is the fixed batch size, X is 0.
                    await poll(
                        () => getInsightWithRetrySpy.mock.calls.length >= 2,
                        'Timed out waiting for insight fetches to start'
                    )
                    expect(logic.values.refreshMetrics).toEqual({ completed: 0, total: 2 })

                    // One tile's query aborts mid-cycle (e.g. a 504). Y must stay pinned at 2 — the pre-fix
                    // selector derived Y from the live map, so it collapsed as the map shrank — and only the
                    // aborted tile leaves the status map, so the sibling still in flight keeps being counted
                    // (a whole-map wipe would drop it and overstate X as "done").
                    logic.actions.abortQuery({ queryId: 'q1', queryStartTime: 0, shortId: insight1.short_id })
                    expect(logic.values.refreshStatus).not.toHaveProperty(insight1.short_id)
                    expect(logic.values.refreshStatus[insight2.short_id]?.loading).toBe(true)
                    expect(logic.values.refreshMetrics).toEqual({ completed: 1, total: 2 })

                    gates[insight1.short_id].release()
                    gates[insight2.short_id].release()
                    await refreshDone
                } finally {
                    Object.values(gates).forEach(({ release }) => release())
                    getInsightWithRetrySpy.mockRestore()
                    cancelQuerySpy.mockRestore()
                }
            })

            it('save during in-flight dashboard refresh does not abort insight fetches', async () => {
                const dashboard = dashboards[5]
                const insight1 = dashboard.tiles[0].insight!
                const insight2 = dashboard.tiles[1].insight!

                let releaseBarrier: () => void
                const barrier = new Promise<void>((resolve): void => {
                    releaseBarrier = resolve
                })

                const realGetInsightWithRetry =
                    jest.requireActual<typeof dashboardUtils>('./dashboardUtils').getInsightWithRetry

                const getInsightWithRetrySpy = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation(
                        async (
                            ...args: Parameters<typeof realGetInsightWithRetry>
                        ): ReturnType<typeof realGetInsightWithRetry> => {
                            await barrier
                            return realGetInsightWithRetry(...args)
                        }
                    )

                try {
                    ;(api.update as jest.Mock).mockClear()

                    // forceRefresh: true so every insight tile hits getInsightWithRetry because preview can skip fresh tiles
                    const refreshDone = expectLogic(logic, () => {
                        logic.actions.triggerDashboardRefresh()
                    }).toFinishAllListeners()

                    const deadline = Date.now() + 5000
                    while (getInsightWithRetrySpy.mock.calls.length < 2) {
                        if (Date.now() > deadline) {
                            throw new Error('Timed out waiting for insight fetches to start')
                        }
                        await new Promise((r) => setTimeout(r, 0))
                    }

                    const firstTile = dashboard.tiles[0]
                    const currentLayouts = logic.values.layouts
                    const modifiedLayouts: any = {
                        ...currentLayouts,
                        sm: currentLayouts.sm?.map((layout) =>
                            layout.i === String(firstTile.id) ? { ...layout, x: (layout.x ?? 0) + 1 } : layout
                        ),
                    }

                    logic.actions.updateLayouts(modifiedLayouts)
                    logic.actions.saveLayoutChanges()

                    // Do not use toFinishAllListeners here: it would wait for refreshDashboardItems too,
                    // while refresh is intentionally blocked on `barrier`.
                    const saveDeadline = Date.now() + 5000
                    while ((api.update as jest.Mock).mock.calls.length < 1) {
                        if (Date.now() > saveDeadline) {
                            throw new Error('Timed out waiting for saveEditModeChanges to call api.update')
                        }
                        await new Promise((r) => setTimeout(r, 0))
                    }
                    expect(api.update).toHaveBeenCalledTimes(1)

                    releaseBarrier!()
                    await refreshDone

                    expect(logic.values.refreshStatus[insight1.short_id]?.refreshed).toBe(true)
                    expect(logic.values.refreshStatus[insight2.short_id]?.refreshed).toBe(true)
                } finally {
                    releaseBarrier!()
                    getInsightWithRetrySpy.mockRestore()
                }
            })

            it('manual refresh does not update last refresh when insights fail', async () => {
                const dashboard = dashboards[5]
                const insight1 = dashboard.tiles[0].insight!
                const insight2 = dashboard.tiles[1].insight!
                const refreshError = new Error('Queries are a little too busy right now.')
                const getInsightWithRetrySpy = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockRejectedValue(refreshError)
                ;(api.update as jest.Mock).mockClear()

                await expectLogic(logic, () => {
                    logic.actions.triggerDashboardRefresh()
                })
                    .toDispatchActions([
                        'triggerDashboardRefresh',
                        'refreshDashboardItems',
                        logic.actionCreators.setRefreshStatuses([insight1.short_id, insight2.short_id], false, true),
                    ])
                    .toFinishAllListeners()

                expect(logic.values.lastDashboardRefresh).toBeNull()
                expect(logic.values.blockRefresh).toBe(false)
                expect(api.update).not.toHaveBeenCalled()

                getInsightWithRetrySpy.mockRestore()
            })

            it('shows query status errors returned in serialized insights', async () => {
                const dashboard = dashboards[5]
                const insight1 = dashboard.tiles[0].insight!
                const insight2 = dashboard.tiles[1].insight!
                const getInsightWithRetrySpy = jest.spyOn(dashboardUtils, 'getInsightWithRetry').mockResolvedValue({
                    ...insight1,
                    query_status: {
                        id: 'failed-query-id',
                        query_async: true,
                        team_id: MOCK_TEAM_ID,
                        error: true,
                        complete: true,
                        error_message: 'This query ran out of memory before it could finish',
                        error_code: 'query_memory_limit',
                    },
                })

                await expectLogic(logic, () => {
                    logic.actions.triggerDashboardRefresh()
                }).toFinishAllListeners()

                for (const insight of [insight1, insight2]) {
                    expect(logic.values.refreshStatus[insight.short_id]).toMatchObject({
                        errored: true,
                        error: expect.objectContaining({
                            detail: 'This query ran out of memory before it could finish',
                            code: 'query_memory_limit',
                        }),
                    })
                }

                getInsightWithRetrySpy.mockRestore()
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

        describe('page visibility', () => {
            it('pauses auto-refresh when page is hidden and resumes when visible', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAutoRefresh(true, 900)
                })
                    .toDispatchActions(['setAutoRefresh', 'resetInterval'])
                    .toMatchValues({
                        autoRefresh: { enabled: true, interval: 900 },
                    })

                await expectLogic(logic, () => {
                    logic.actions.setPageVisibility(false)
                }).toDispatchActions(['setPageVisibility'])

                await expectLogic(logic, () => {
                    logic.actions.setPageVisibility(true)
                }).toDispatchActions(['setPageVisibility', 'resetInterval'])
            })

            it('does not restart auto-refresh on page visible if auto-refresh is disabled', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAutoRefresh(false, 1800)
                })
                    .toDispatchActions(['setAutoRefresh'])
                    .toMatchValues({
                        autoRefresh: { enabled: false, interval: 1800 },
                    })

                await expectLogic(logic, () => {
                    logic.actions.setPageVisibility(true)
                })
                    .toDispatchActions(['setPageVisibility'])
                    .toNotHaveDispatchedActions(['resetInterval'])
            })
        })
    })

    describe('dashboard variables', () => {
        const variableId = '019d4e3a-3ae0-0000-0698-96f9eecd74ef'
        const baseVariable = {
            code_name: 'organization',
            variableId,
        }

        const mountDashboardWithVariable = async ({
            urlValue,
            dashboardOverride,
            insightOverride,
            insightCount = 1,
        }: {
            urlValue?: string | null
            dashboardOverride?: Partial<HogQLVariable>
            insightOverride?: Partial<HogQLVariable>
            insightCount?: number
        }): Promise<void> => {
            router.actions.push(
                '/',
                urlValue === undefined
                    ? {}
                    : {
                          [dashboardUtils.SEARCH_PARAM_QUERY_VARIABLES_KEY]: JSON.stringify({
                              organization: urlValue,
                          }),
                      }
            )

            const insightWithVariable = {
                ...insightOnDashboard(175, [12]),
                query: {
                    kind: NodeKind.DataVisualizationNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: 'select {variables.organization}',
                        variables: {
                            [variableId]: {
                                ...baseVariable,
                                ...insightOverride,
                            },
                        },
                    },
                    chartSettings: {},
                    tableSettings: {},
                } as any,
            }

            const dashboardWithVariableOverride = {
                ...dashboardResult(12, [
                    tileFromInsight(insightWithVariable),
                    ...Array.from({ length: insightCount - 1 }, (_, index) =>
                        tileFromInsight({
                            ...insightWithVariable,
                            id: 176 + index,
                            short_id: `retry-${index}` as InsightShortId,
                        })
                    ),
                ]),
                persisted_variables: dashboardOverride
                    ? {
                          [variableId]: {
                              ...baseVariable,
                              ...dashboardOverride,
                          },
                      }
                    : undefined,
            }

            // The logic re-fetches the dashboard on mount; without this the unhandled-request
            // floor returns a shape without tiles
            // oxlint-disable-next-line react-hooks/rules-of-hooks
            useMocks({
                get: {
                    '/api/environments/:team_id/dashboards/12/': () => [200, dashboardWithVariableOverride],
                },
            })

            variableDataLogic.mount()
            logic = dashboardLogic({ id: 12, dashboard: dashboardWithVariableOverride })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(variableDataLogic, () => {
                variableDataLogic.actions.loadVariablesSuccess([
                    {
                        id: variableId,
                        name: 'Organization',
                        code_name: 'organization',
                        type: 'String',
                        default_value: 'Default org',
                    },
                ] as any)
            }).toMatchValues({
                variables: [
                    expect.objectContaining({
                        id: variableId,
                        code_name: 'organization',
                    }),
                ],
            })
        }

        const popToSearchParams = async (searchParams: Record<string, string>): Promise<void> => {
            await expectLogic(logic, () => {
                router.actions.locationChanged({
                    method: 'POP',
                    pathname: '/dashboard/12',
                    search: '',
                    searchParams,
                    hash: '',
                    hashParams: {},
                    url: '/dashboard/12',
                })
            }).toFinishAllListeners()
        }

        it.each([
            ['url override (non-null)', 'url-val', undefined, undefined, 'url-val', false],
            ['url override (null)', null, undefined, undefined, null, true],
            ['persisted null override', undefined, { value: null, isNull: true }, undefined, null, true],
            ['insight value fallback', undefined, undefined, { value: 'insight' }, 'insight', undefined],
            ['default value fallback', undefined, undefined, undefined, 'Default org', undefined],
        ])(
            'resolves variable value: %s',
            async (
                _name: string,
                urlValue: string | null | undefined,
                dashboardOverride: Partial<HogQLVariable> | undefined,
                insightOverride: Partial<HogQLVariable> | undefined,
                expectedValue: string | null,
                expectedIsNull: boolean | undefined
            ) => {
                await mountDashboardWithVariable({ urlValue, dashboardOverride, insightOverride })

                expect(logic.values.effectiveVariablesAndAssociatedInsights).toEqual([
                    {
                        variable: expect.objectContaining({
                            id: variableId,
                            name: 'Organization',
                            code_name: 'organization',
                            value: expectedValue,
                            isNull: expectedIsNull,
                        }),
                        insightNames: ['donut'],
                    },
                ])
            }
        )

        it('shows and saves a URL variable override as unsaved settings', async () => {
            await mountDashboardWithVariable({ urlValue: 'url-val' })
            const update = jest.spyOn(api, 'update').mockResolvedValue({
                ...logic.values.dashboard!,
                persisted_variables: {
                    [variableId]: { ...baseVariable, value: 'url-val', isNull: false },
                },
            })

            expect(logic.values.urlVariables).toEqual({
                [variableId]: expect.objectContaining({ code_name: 'organization', value: 'url-val' }),
            })
            expect(logic.values.filtersDirty).toBe(false)
            expect(logic.values.filterChanges).toEqual([])
            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')

            await expectLogic(logic, () => {
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(update).toHaveBeenCalledWith(expect.any(String), {
                filters: {},
                variables: {
                    [variableId]: expect.objectContaining({ value: 'url-val' }),
                },
            })
            expect(router.values.searchParams).toEqual({})
            expect(logic.values.dashboardSettingsState).toBe('saved')
        })

        it('shows filter edits as unsaved when a URL variable override exists', async () => {
            await mountDashboardWithVariable({ urlValue: 'url-val' })

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: false },
                    DashboardEventSource.DashboardFilters
                )
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            expect(logic.values.filtersDirty).toBe(true)
            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')
        })

        it('treats selecting the SQL variable default as saved', async () => {
            await mountDashboardWithVariable({})

            await expectLogic(logic, () => {
                logic.actions.overrideVariableValue(variableId, 'Default org', false)
            }).toFinishAllListeners()

            expect(logic.values.dashboardSettingsState).toBe('saved')
            expect(logic.values.dashboardSettingsChanges).toEqual([])
            expect(router.values.searchParams).toEqual({})
        })

        const historyCases: [string, Record<string, string>, string][] = [
            [
                'restores the override the URL carries',
                { [dashboardUtils.SEARCH_PARAM_QUERY_VARIABLES_KEY]: JSON.stringify({ organization: 'url-val' }) },
                'url-val',
            ],
            ['restores the saved value when the URL drops the override', {}, 'persisted'],
        ]

        it.each(historyCases)('browser history moves SQL variables: %s', async (_name, searchParams, expectedValue) => {
            await mountDashboardWithVariable({
                urlValue: 'url-val',
                dashboardOverride: { value: 'persisted', isNull: false },
            })

            await expectLogic(logic, () => {
                logic.actions.overrideVariableValue(variableId, 'edited', false)
            }).toFinishAllListeners()

            await popToSearchParams(searchParams)

            expect(logic.values.currentDashboardSettings.variables[variableId]).toEqual(
                expect.objectContaining({ value: expectedValue })
            )
        })

        it('keeps the chosen default in the URL when the dashboard saved another value', async () => {
            await mountDashboardWithVariable({ dashboardOverride: { value: 'persisted', isNull: false } })

            await expectLogic(logic, () => {
                logic.actions.overrideVariableValue(variableId, 'Default org', false)
            }).toFinishAllListeners()

            expect(dashboardUtils.parseURLVariables(router.values.searchParams)).toEqual({
                organization: 'Default org',
            })
            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')
        })

        it('discards filter and SQL variable changes and restores the saved settings', async () => {
            await mountDashboardWithVariable({ urlValue: 'url-val' })
            router.actions.push('/', {
                [dashboardUtils.SEARCH_PARAM_FILTERS_KEY]: JSON.stringify({ date_from: '-7d' }),
                [dashboardUtils.SEARCH_PARAM_QUERY_VARIABLES_KEY]: JSON.stringify({ organization: 'url-val' }),
            })

            await expectLogic(logic, () => {
                logic.actions.setDates('-30d', null)
                logic.actions.overrideVariableValue(variableId, 'edited', false)
                logic.actions.discardDashboardChanges()
            }).toFinishAllListeners()

            expect(router.values.searchParams).toEqual({})
            expect(logic.values.currentDashboardSettings).toEqual({ filters: {}, variables: {} })
        })

        it('saves filter and SQL variable edits in one dashboard update', async () => {
            await mountDashboardWithVariable({
                urlValue: 'url-override',
                dashboardOverride: { value: 'persisted', isNull: false },
            })
            const updatedDashboard = {
                ...logic.values.dashboard!,
                persisted_filters: { date_from: '-7d', date_to: null },
                persisted_variables: {
                    [variableId]: { ...baseVariable, value: 'edited', isNull: false },
                },
            }
            const update = jest.spyOn(api, 'update').mockResolvedValue(updatedDashboard)

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
                logic.actions.overrideVariableValue(variableId, 'edited', false)
                logic.actions.saveDashboardChanges()
            }).toFinishAllListeners()

            expect(update).toHaveBeenCalledWith(expect.any(String), {
                filters: { date_from: '-7d', date_to: null },
                variables: {
                    [variableId]: expect.objectContaining({ value: 'edited' }),
                },
            })
            expect(router.values.searchParams).toEqual({})
            expect(logic.values.dashboardSettingsState).toBe('saved')
        })

        it('keeps edits made while dashboard changes save', async () => {
            await mountDashboardWithVariable({})
            let finishSave: (dashboard: DashboardType) => void = () => {
                throw new Error('Save resolver is unavailable')
            }
            const save = new Promise<DashboardType>((resolve) => {
                finishSave = resolve
            })
            jest.spyOn(api, 'update').mockReturnValueOnce(save)

            logic.actions.overrideVariableValue(variableId, 'submitted', false)
            logic.actions.saveDashboardChanges()
            await expectLogic(logic).toMatchValues({ dashboardFiltersSaving: true })

            logic.actions.overrideVariableValue(variableId, 'newer edit', false)
            finishSave({
                ...logic.values.dashboard!,
                persisted_variables: {
                    [variableId]: { ...baseVariable, value: 'submitted', isNull: false },
                },
            })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dashboardSettingsState).toBe('unsavedChanges')
            expect(logic.values.currentDashboardSettings.variables[variableId]).toEqual(
                expect.objectContaining({ value: 'newer edit' })
            )
        })

        it.each(['dashboard', 'individual tile'] as const)(
            'keeps the variable change ID and total wait through a failed refresh and %s retry',
            async (retry) => {
                const autoPreviewLimit = jest.replaceProperty(dashboardUtils, 'AUTO_PREVIEW_TILE_LIMIT', 0)
                await mountDashboardWithVariable({ insightCount: 3 })
                const capture = jest.spyOn(posthog, 'capture').mockClear()
                const clock = jest.spyOn(performance, 'now').mockReturnValue(1000)
                const refresh = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation(async (_teamId, insight) => insight)
                    .mockRejectedValueOnce(new Error('First tile failed'))
                    .mockRejectedValueOnce(new Error('Second tile failed'))

                try {
                    await expectLogic(logic, () => {
                        logic.actions.overrideVariableValue(variableId, 'edited', false)
                    }).toFinishAllListeners()

                    expect(logic.values.canAutoPreview).toBe(false)
                    expect(refresh).not.toHaveBeenCalled()
                    expect(dashboardUtils.parseURLVariables(router.values.searchParams)).toEqual({
                        organization: 'edited',
                    })
                    const change = capture.mock.calls.find(([event]) => event === 'dashboard filters changed')![1]!
                    expect(capture.mock.calls.some(([event]) => event === 'dashboard refreshed')).toBe(false)

                    clock.mockReturnValue(6000)
                    await expectLogic(logic, () => {
                        if (retry === 'individual tile') {
                            jest.spyOn(api, 'update').mockResolvedValueOnce({
                                ...logic.values.dashboard!,
                                persisted_variables: logic.values.currentDashboardSettings.variables,
                            })
                            logic.actions.saveDashboardChanges()
                        } else {
                            logic.actions.previewDashboardChanges()
                        }
                    }).toFinishAllListeners()
                    expect(capture).toHaveBeenCalledWith(
                        'dashboard refreshed',
                        expect.objectContaining({
                            filter_change_id: change.filter_change_id,
                            filter_change_duration_ms: 5000,
                            all_insights_succeeded: false,
                            tiles_errored_count: 2,
                        })
                    )

                    clock.mockReturnValue(9000)
                    if (retry === 'individual tile') {
                        await expectLogic(logic, () => {
                            logic.actions.refreshDashboardItem({ tile: logic.values.insightTiles[0] })
                        }).toFinishAllListeners()
                        expect(capture).toHaveBeenCalledWith(
                            'dashboard insight refreshed',
                            expect.objectContaining({
                                filter_change_id: change.filter_change_id,
                                filter_change_duration_ms: 8000,
                                all_insights_succeeded: false,
                            })
                        )
                        clock.mockReturnValue(10000)
                        await expectLogic(logic, () => {
                            logic.actions.refreshDashboardItem({ tile: logic.values.insightTiles[1] })
                        }).toFinishAllListeners()
                    } else {
                        await expectLogic(logic, () => logic.actions.previewDashboardChanges()).toFinishAllListeners()
                    }
                    const resultEvent =
                        retry === 'individual tile' ? 'dashboard insight refreshed' : 'dashboard refreshed'
                    const elapsed = retry === 'individual tile' ? 9000 : 8000
                    expect(capture).toHaveBeenCalledWith(
                        resultEvent,
                        expect.objectContaining({
                            filter_change_id: change.filter_change_id,
                            filter_change_duration_ms: elapsed,
                            all_insights_succeeded: true,
                        })
                    )
                } finally {
                    refresh.mockRestore()
                    clock.mockRestore()
                    autoPreviewLimit.restore()
                }
            }
        )

        it.each(['manual', 'saved insight'])(
            'uses dashboard context for a %s tile refresh before Preview',
            async (trigger) => {
                const autoPreviewLimit = jest.replaceProperty(dashboardUtils, 'AUTO_PREVIEW_TILE_LIMIT', 0)
                await mountDashboardWithVariable({})
                const getInsightWithRetrySpy = jest
                    .spyOn(dashboardUtils, 'getInsightWithRetry')
                    .mockImplementation(async (_teamId, insight) => insight)

                try {
                    await expectLogic(logic, () => {
                        logic.actions.overrideVariableValue(variableId, 'draft value', false)
                    }).toFinishAllListeners()

                    await expectLogic(logic, () => {
                        if (trigger === 'saved insight') {
                            insightsModel.actions.insightSaved(logic.values.insightTiles[0].insight!.short_id)
                        } else {
                            logic.actions.refreshDashboardItem({ tile: logic.values.insightTiles[0] })
                        }
                    }).toFinishAllListeners()

                    expect(getInsightWithRetrySpy).toHaveBeenCalledTimes(1)
                    expect(getInsightWithRetrySpy.mock.calls[0][6]).toEqual(logic.values.effectiveRefreshFilters)
                    expect(getInsightWithRetrySpy.mock.calls[0][7]).toEqual({})
                    expect(getInsightWithRetrySpy.mock.calls[0][8]).toEqual(
                        logic.values.insightTiles[0].filters_overrides
                    )
                } finally {
                    getInsightWithRetrySpy.mockRestore()
                    autoPreviewLimit.restore()
                }
            }
        )

        it.each(['edit', 'discard', 'unmount'] as const)(
            'keeps older Preview results separate after %s and tracks the next valid results',
            async (transition) => {
                const autoPreviewLimit = jest.replaceProperty(dashboardUtils, 'AUTO_PREVIEW_TILE_LIMIT', 0)
                await mountDashboardWithVariable({})
                const capture = jest.spyOn(posthog, 'capture').mockClear()
                await expectLogic(logic, () => {
                    logic.actions.overrideVariableValue(variableId, 'first value', false)
                }).toFinishAllListeners()
                const change = capture.mock.calls.find(([event]) => event === 'dashboard filters changed')![1]!
                let finishPreview!: (insight: InsightModel) => void
                const preview = new Promise<InsightModel>((resolve) => {
                    finishPreview = resolve
                })
                const refresh = jest.spyOn(dashboardUtils, 'getInsightWithRetry').mockReturnValue(preview)
                const insight = logic.values.insightTiles[0].insight!

                try {
                    await expectLogic(logic, () => logic.actions.previewDashboardChanges()).toDispatchActions([
                        'setRefreshStatus',
                    ])
                    expect(logic.values.loadingPreview).toBe(true)

                    if (transition === 'edit') {
                        logic.actions.overrideVariableValue(variableId, 'newer value', false)
                        expect(logic.values.loadingPreview).toBe(false)
                        expect(capture).toHaveBeenCalledWith(
                            'dashboard filters changed',
                            expect.objectContaining({ supersedes_filter_change_id: change.filter_change_id })
                        )
                    } else if (transition === 'discard') {
                        logic.actions.discardDashboardChanges()
                    } else {
                        logic.unmount()
                    }

                    finishPreview(insight)
                    await expectLogic(logic).toFinishAllListeners()
                    expect(capture).not.toHaveBeenCalledWith(
                        'dashboard refreshed',
                        expect.objectContaining({ filter_change_id: change.filter_change_id })
                    )
                    if (transition === 'edit') {
                        expect(logic.values.previewedDashboardSettings?.variables[variableId].value).toBe('first value')
                        expect(logic.values.currentDashboardSettings.variables[variableId].value).toBe('newer value')
                    }

                    refresh.mockImplementation(async (_teamId, insight) => insight)
                    if (transition === 'unmount') {
                        await mountDashboardWithVariable({})
                    }
                    if (transition !== 'edit') {
                        logic.actions.overrideVariableValue(variableId, 'newer value', false)
                    }
                    await expectLogic(logic, () => logic.actions.previewDashboardChanges()).toFinishAllListeners()
                    const latestChange = capture.mock.calls
                        .filter(([event]) => event === 'dashboard filters changed')
                        .at(-1)![1]!
                    expect(latestChange.filter_change_id).not.toBe(change.filter_change_id)
                    expect(capture).toHaveBeenCalledWith(
                        'dashboard refreshed',
                        expect.objectContaining({
                            filter_change_id: latestChange.filter_change_id,
                            all_insights_succeeded: true,
                        })
                    )
                } finally {
                    refresh.mockRestore()
                    autoPreviewLimit.restore()
                }
            }
        )

        it('applying a variable value refreshes every tile with the new value attached to the request', async () => {
            await mountDashboardWithVariable({})
            const capture = jest.spyOn(posthog, 'capture').mockClear()

            const getInsightWithRetrySpy = jest
                .spyOn(dashboardUtils, 'getInsightWithRetry')
                .mockImplementation(async (_teamId, insight) => insight)

            try {
                await expectLogic(logic, () => {
                    logic.actions.overrideVariableValue(variableId, 'applied-value', false)
                })
                    .toDispatchActions(['overrideVariableValue', 'refreshDashboardItems'])
                    .toFinishAllListeners()

                expect(logic.values.effectiveVariablesAndAssociatedInsights[0].variable.value).toBe('applied-value')
                expect(getInsightWithRetrySpy).toHaveBeenCalledTimes(1)
                const variablesOverride = getInsightWithRetrySpy.mock.calls[0][7]
                expect(variablesOverride).toEqual({
                    [variableId]: expect.objectContaining({ code_name: 'organization', value: 'applied-value' }),
                })
                const change = capture.mock.calls.find(([event]) => event === 'dashboard filters changed')![1]!
                expect(capture).toHaveBeenCalledWith(
                    'dashboard refreshed',
                    expect.objectContaining({
                        filter_change_id: change.filter_change_id,
                        all_insights_succeeded: true,
                    })
                )
            } finally {
                getInsightWithRetrySpy.mockRestore()
            }
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

        it('refreshing a shared insight on one dashboard does not change its date range on another dashboard', async () => {
            const nineLogic = dashboardLogic({ id: 9 })
            const tenLogic = dashboardLogic({ id: 10 })
            nineLogic.mount()
            tenLogic.mount()
            await expectLogic(nineLogic).toFinishAllListeners()
            await expectLogic(tenLogic).toFinishAllListeners()

            const copiedInsight = insight800()
            const insightQuery = copiedInsight.query as InsightVizNode<TrendsQuery> | undefined
            const payload = {
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
            }

            dashboardsModel.actions.updateDashboardInsight(payload, undefined, 10)

            await expectLogic(nineLogic).toFinishAllListeners()
            const nineQuery = nineLogic.values.insightTiles[0].insight?.query as InsightVizNode<TrendsQuery> | undefined
            expect(nineQuery?.source?.dateRange?.date_from).toBeUndefined()
            expect(nineQuery?.source?.interval).toEqual('day')

            const tenQuery = tenLogic.values.insightTiles[0].insight?.query as InsightVizNode<TrendsQuery> | undefined
            expect(tenQuery?.source?.dateRange?.date_from).toEqual('-1d')
            expect(tenQuery?.source?.interval).toEqual('hour')
        })

        it('can respond to external insight rename', async () => {
            expect(logic.values.dashboard?.tiles[0].color).toEqual(null)

            const copiedInsight = insight800()
            insightsModel.actions.renameInsightSuccess({
                ...copiedInsight,
                name: 'renamed',
                last_modified_at: '2021-04-01 12:00:00',
                description: 'updated description',
            })

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.dashboard?.tiles).toHaveLength(2)
            expect(logic.values.insightTiles[0].insight!.name).toEqual('renamed')
            expect(logic.values.insightTiles[0].insight!.last_modified_at).toEqual('2021-04-01 12:00:00')
            expect(logic.values.insightTiles[0].insight!.description).toEqual('updated description')
            expect(logic.values.textTiles[0].text!.body).toEqual('I AM A TEXT')
        })

        it('preserves cached chart data when a bare PATCH returns null result', async () => {
            // insight800() has non-null result and last_refresh from the fixture; a bare PATCH
            // (rename, display-option save) responds with result: null. The tile must keep its
            // previously-computed chart data rather than blanking to "Chart data didn't load".
            const originalInsight = logic.values.insightTiles[0].insight!
            const originalResult = originalInsight.result
            const originalLastRefresh = originalInsight.last_refresh

            insightsModel.actions.renameInsightSuccess({
                ...insight800(),
                name: 'renamed via bare patch',
                result: null,
                last_refresh: null,
            })

            await expectLogic(logic).toFinishAllListeners()
            const updated = logic.values.insightTiles[0].insight!
            expect(updated.name).toEqual('renamed via bare patch')
            expect(updated.result).toEqual(originalResult)
            expect(updated.last_refresh).toEqual(originalLastRefresh)
        })

        it('preserves cached columns and types when a bare PATCH returns them null', async () => {
            // SQL tiles draw from columns and types rather than result, and pick their axes from
            // columns. Blanking those leaves the tile with nothing to draw.
            insightsModel.actions.renameInsightSuccess({
                ...insight800(),
                columns: ['day', 'total'],
                types: [
                    ['day', 'DateTime'],
                    ['total', 'UInt64'],
                ],
            })
            await expectLogic(logic).toFinishAllListeners()

            insightsModel.actions.renameInsightSuccess({
                ...insight800(),
                name: 'renamed via bare patch',
                columns: null,
                types: null,
            })
            await expectLogic(logic).toFinishAllListeners()

            const updated = logic.values.insightTiles[0].insight!
            expect(updated.name).toEqual('renamed via bare patch')
            expect(updated.columns).toEqual(['day', 'total'])
            expect(updated.types).toEqual([
                ['day', 'DateTime'],
                ['total', 'UInt64'],
            ])
        })

        it('preserves sync warnings when a bare PATCH returns them null', async () => {
            const warning = {
                type: 'warehouse_sync' as const,
                message: 'Last sync of `invoices` (from Stripe) failed.',
                schema_name: 'invoices',
                source_id: 'source-1',
                source_type: 'Stripe',
                status: 'Failed',
                table_name: 'stripe_invoices',
            }
            insightsModel.actions.renameInsightSuccess({ ...insight800(), warnings: [warning] })
            await expectLogic(logic).toFinishAllListeners()

            insightsModel.actions.renameInsightSuccess({
                ...insight800(),
                name: 'renamed via bare patch',
                warnings: null,
            })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.insightTiles[0].insight!.warnings).toEqual([warning])
        })

        it('replaces cached chart data when a full refresh returns non-null result', async () => {
            const newResult = [{ data: 'fresh' }]
            const newLastRefresh = '2024-01-01T00:00:00Z'

            insightsModel.actions.renameInsightSuccess({
                ...insight800(),
                name: 'refreshed',
                result: newResult,
                last_refresh: newLastRefresh,
            })

            await expectLogic(logic).toFinishAllListeners()
            const updated = logic.values.insightTiles[0].insight!
            expect(updated.name).toEqual('refreshed')
            expect(updated.result).toEqual(newResult)
            expect(updated.last_refresh).toEqual(newLastRefresh)
        })

        it('can respond to external insight update for an insight tile that is new on this dashboard', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.updateDashboardInsight({
                    short_id: 'not_already_on_the_dashboard' as InsightShortId,
                } as InsightModel)
            })
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboard'])
        })

        it('reloads when an external rename lands before the tile is in state', async () => {
            await expectLogic(logic, () => {
                insightsModel.actions.renameInsightSuccess({
                    ...insight800(),
                    short_id: 'not_already_on_the_dashboard' as InsightShortId,
                    dashboard_tiles: [{ id: 1, dashboard_id: 9 }],
                })
            })
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboard'])
        })

        it('does not reload when an external rename targets a different dashboard only', async () => {
            const loadDashboardSpy = jest.spyOn(logic.actions, 'loadDashboard')
            await expectLogic(logic, () => {
                insightsModel.actions.renameInsightSuccess({
                    ...insight800(),
                    short_id: 'not_already_on_the_dashboard' as InsightShortId,
                    dashboard_tiles: [{ id: 1, dashboard_id: 10 }],
                })
            }).toFinishAllListeners()
            expect(loadDashboardSpy).not.toHaveBeenCalled()
        })
    })

    describe('text tiles', () => {
        let lemonToastInfoSpy: jest.SpiedFunction<typeof lemonToast.info>

        beforeEach(async () => {
            lemonToastInfoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast-id')
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => {
            lemonToastInfoSpy.mockRestore()
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

        it('shows undo toast when removing a text tile', async () => {
            const { render } = await import('@testing-library/react')

            await expectLogic(logic, () => {
                logic.actions.removeTile(TEXT_TILE)
            }).toFinishAllListeners()

            expect(lemonToastInfoSpy).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    toastId: `remove-tile-${TEXT_TILE.id}`,
                    button: expect.objectContaining({ label: 'Undo' }),
                })
            )

            const toastContent = lemonToastInfoSpy.mock.calls.at(-1)?.[0]
            const { container } = render(toastContent)
            expect(container.textContent).toBe('Text card has been removed from the dashboard')
        })

        it('removes the tile from state optimistically before the API call resolves', async () => {
            expect(logic.values.textTiles).toHaveLength(1)

            // Dispatch without awaiting listeners — the reducer drops the tile synchronously.
            logic.actions.removeTile(TEXT_TILE)

            expect(logic.values.textTiles).toEqual([])

            // Let the in-flight listener settle before teardown unmounts the logic
            await expectLogic(logic).toFinishAllListeners()
        })

        it('restores the tile and suppresses the undo toast when the API call fails', async () => {
            const updateSpy = jest.spyOn(api, 'update').mockRejectedValueOnce(new Error('boom'))
            const lemonToastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')

            await expectLogic(logic, () => {
                logic.actions.removeTile(TEXT_TILE)
            }).toFinishAllListeners()

            // Tile is back in place, the error toast fired, and no undo toast was shown.
            expect(logic.values.textTiles).toHaveLength(1)
            expect(lemonToastErrorSpy).toHaveBeenCalled()
            expect(lemonToastInfoSpy).not.toHaveBeenCalled()

            updateSpy.mockRestore()
            lemonToastErrorSpy.mockRestore()
        })
    })

    describe('insight tiles', () => {
        let lemonToastInfoSpy: jest.SpiedFunction<typeof lemonToast.info>
        let lemonToastDismissSpy: jest.SpiedFunction<typeof lemonToast.dismiss>
        let lemonDialogOpenSpy: jest.SpiedFunction<typeof LemonDialog.open>

        beforeEach(async () => {
            lemonToastInfoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast-id')
            lemonToastDismissSpy = jest.spyOn(lemonToast, 'dismiss').mockImplementation(() => undefined)
            lemonDialogOpenSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => undefined)
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => {
            lemonToastInfoSpy.mockRestore()
            lemonToastDismissSpy.mockRestore()
            lemonDialogOpenSpy.mockRestore()
        })

        it('offers to delete a removed insight and explains its other dashboard usage', async () => {
            const { fireEvent, render } = await import('@testing-library/react')
            const reportDeleteClicked = jest.spyOn(
                eventUsageLogic.actions,
                'reportDashboardInsightDeleteAfterRemovalClicked'
            )
            const insightTile = logic.values.insightTiles[0]
            const insight = insightTile.insight!

            await expectLogic(logic, () => {
                logic.actions.removeTile({
                    ...insightTile,
                    insight: {
                        ...insight,
                        dashboard_tiles: [
                            ...(insight.dashboard_tiles || []),
                            { id: 999, dashboard_id: 8, deleted: true },
                        ],
                    },
                })
            }).toFinishAllListeners()

            const toastContent = lemonToastInfoSpy.mock.calls.at(-1)?.[0]
            const { getByText } = render(toastContent)
            fireEvent.click(getByText('Delete insight everywhere'))
            expect(reportDeleteClicked).toHaveBeenCalledWith(1)
            expect(lemonToastDismissSpy).not.toHaveBeenCalled()

            const dialogProps = lemonDialogOpenSpy.mock.calls.at(-1)?.[0]
            expect(dialogProps).toEqual(
                expect.objectContaining({ title: 'Delete insight everywhere?', shouldAwaitSubmit: true })
            )
            if (!dialogProps) {
                throw new Error('Delete dialog did not open')
            }

            const { container, getByText: getDialogText } = render(dialogProps.description)
            expect(getDialogText('This insight is also used on:')).not.toBeNull()
            expect(container.querySelector('a')?.getAttribute('href')).toMatch(/\/dashboard\/6$/)
            expect(
                getDialogText('This deletes the insight and removes it from every dashboard. You can undo this action.')
            ).not.toBeNull()

            reportDeleteClicked.mockRestore()
        })
    })

    describe('widget tiles', () => {
        let lemonToastInfoSpy: jest.SpiedFunction<typeof lemonToast.info>

        beforeEach(async () => {
            lemonToastInfoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast-id')
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => {
            lemonToastInfoSpy.mockRestore()
        })

        it('shows undo toast with widget name when removing a widget tile', async () => {
            const { render } = await import('@testing-library/react')

            await expectLogic(logic, () => {
                logic.actions.removeTile(WIDGET_TILE)
            }).toFinishAllListeners()

            expect(lemonToastInfoSpy).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    toastId: `remove-tile-${WIDGET_TILE.id}`,
                    button: expect.objectContaining({ label: 'Undo' }),
                })
            )

            const toastContent = lemonToastInfoSpy.mock.calls.at(-1)?.[0]
            const { container } = render(toastContent)
            expect(container.textContent).toBe('Top issues widget removed')
        })

        it('uses custom widget name in undo toast when set', async () => {
            const { render } = await import('@testing-library/react')

            await expectLogic(logic, () => {
                logic.actions.removeTile(WIDGET_TILE_WITH_CUSTOM_NAME)
            }).toFinishAllListeners()

            const toastContent = lemonToastInfoSpy.mock.calls.at(-1)?.[0]
            const { container } = render(toastContent)
            expect(container.textContent).toBe('Critical errors widget removed')
        })
    })

    describe('layout zoom', () => {
        beforeEach(async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('clamps layoutZoom between 0.25 and 1', async () => {
            await expectLogic(logic).toMatchValues({ layoutZoom: 1 })

            await expectLogic(logic, () => {
                logic.actions.setLayoutZoom(2)
            }).toMatchValues({ layoutZoom: 1 })

            await expectLogic(logic, () => {
                logic.actions.setLayoutZoom(0.1)
            }).toMatchValues({ layoutZoom: 0.25 })

            await expectLogic(logic, () => {
                logic.actions.setLayoutZoom(0.75)
            }).toMatchValues({ layoutZoom: 0.75 })

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: false },
                    DashboardEventSource.DashboardFilters
                )
            }).toMatchValues({ layoutZoom: 0.75 })

            await expectLogic(logic, () => {
                logic.actions.setDashboardEditing(
                    { filters: true, layout: true },
                    DashboardEventSource.SceneCommonButtons
                )
                logic.actions.cancelLayoutEdit()
            }).toMatchValues({ layoutZoom: 1 })
        })

        it('resets layoutZoom to 1 when container becomes single-column', async () => {
            await expectLogic(logic, () => {
                logic.actions.setLayoutZoom(0.25)
            }).toMatchValues({ layoutZoom: 0.25 })

            await expectLogic(logic, () => {
                // columns === 1 -> xs layout
                logic.actions.updateContainerWidth(400, 1)
            }).toMatchValues({ layoutZoom: 1 })

            await expectLogic(logic, () => {
                // moving back to multi-column should not change zoom
                logic.actions.setLayoutZoom(0.5)
                logic.actions.updateContainerWidth(1200, 12)
            }).toMatchValues({ layoutZoom: 0.5 })
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
                dashboards: liveDashboardIds(t.insight!.dashboard_tiles),
            }))
        ).toEqual([
            { dashboards: [5, 6], short_id: '172' },
            { dashboards: [5, 6], short_id: '175' },
        ])
        expect(
            nineLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: liveDashboardIds(t.insight!.dashboard_tiles),
            }))
        ).toEqual([{ dashboards: [9, 10], short_id: '800' }])

        // Moved from 9 to 5. The soft-deleted tile on 9 must not count as membership.
        const changedInsight: InsightModel = {
            ...insight800(),
            dashboard_tiles: [
                { id: 1, dashboard_id: 9, deleted: true },
                { id: 2, dashboard_id: 10 },
                { id: 3, dashboard_id: 5 },
            ],
        }
        dashboardsModel.actions.updateDashboardInsight(changedInsight, [9])

        expect(
            fiveLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: liveDashboardIds(t.insight!.dashboard_tiles),
            }))
        ).toEqual([
            { dashboards: [5, 6], short_id: '172' },
            { dashboards: [5, 6], short_id: '175' }, // It's expected that 800 isn't here yet, because we expect to load it from the API for correctness
        ])
        expect(
            nineLogic.values.insightTiles.map((t) => ({
                short_id: t.insight!.short_id,
                dashboards: liveDashboardIds(t.insight!.dashboard_tiles),
            }))
        ).toEqual([])
        // Ensuring we do go back to the API for 800, which was added to dashboard 5
        expectLogic(fiveLogic).toDispatchActions(['loadDashboard']).toFinishAllListeners()
    })

    describe('widget orchestration', () => {
        let fetchRunWidgetsMock: jest.SpiedFunction<typeof widgetFetchUtils.fetchRunWidgets>

        async function makeInsightTilesFresh(): Promise<void> {
            for (const tile of logic.values.insightTiles) {
                if (tile.insight) {
                    await expectLogic(logic, () => {
                        dashboardsModel.actions.updateDashboardInsight(
                            { ...tile.insight!, last_refresh: now().toISOString(), query: tile.insight!.query ?? null },
                            undefined,
                            5
                        )
                    }).toFinishAllListeners()
                }
            }
        }

        beforeEach(() => {
            fetchRunWidgetsMock = jest.spyOn(widgetFetchUtils, 'fetchRunWidgets').mockResolvedValue([
                {
                    tile_id: WIDGET_TILE.id,
                    widget_type: 'error_tracking_list',
                    result: { results: [], hasMore: false },
                    error: null,
                },
            ])

            useMocks({
                get: {
                    '/api/environments/:team_id/dashboards/5/': () => [
                        200,
                        { ...dashboards[5], tiles: [...dashboards[5].tiles, WIDGET_TILE] },
                    ],
                },
            })
        })

        afterEach(() => {
            fetchRunWidgetsMock.mockRestore()
        })

        it('a stale widget releases the shared refresh block', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            await makeInsightTilesFresh()

            const currentTime = Date.now()
            jest.useFakeTimers()
            try {
                jest.setSystemTime(currentTime - 4 * 60_000)
                logic.actions.setWidgetRefreshStatuses([WIDGET_TILE.id], false)
                await jest.advanceTimersByTimeAsync(4 * 60_000)
                logic.actions.updateDashboardLastRefresh(dayjs())
                expect(logic.values.blockRefresh).toBe(true)

                await jest.advanceTimersByTimeAsync(60_100)
                expect(logic.values.blockRefresh).toBe(false)
            } finally {
                jest.useRealTimers()
            }
        })

        it('refreshDashboardWidgets fetches run_widgets for widget tiles', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
            }).toFinishAllListeners()

            expect(fetchRunWidgetsMock).toHaveBeenCalledWith(
                String(MOCK_TEAM_ID),
                5,
                [WIDGET_TILE.id],
                expect.anything()
            )
            expect(logic.values.widgetResultsByTileId[WIDGET_TILE.id]?.result).toEqual({
                results: [],
                hasMore: false,
            })
        })

        it('does not fetch run_widgets on public placement', async () => {
            logic = dashboardLogic({
                id: 5,
                placement: DashboardPlacement.Public,
                dashboard: {
                    ...dashboards[5],
                    tiles: [...dashboards[5].tiles, WIDGET_TILE],
                } as DashboardType,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(fetchRunWidgetsMock).not.toHaveBeenCalled()

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
            }).toFinishAllListeners()

            expect(fetchRunWidgetsMock).not.toHaveBeenCalled()
        })

        it('refreshDashboardWidgets sets friendly error when run_widgets fails', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            await makeInsightTilesFresh()

            const previousFetchedAt = logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.fetchedAt
            logic.actions.updateDashboardLastRefresh(dayjs())
            expect(logic.values.blockRefresh).toBe(true)
            fetchRunWidgetsMock.mockRejectedValueOnce(new Error('Network error'))

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
            }).toFinishAllListeners()

            expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.error).toBe(DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE)
            expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.fetchedAt).toBe(previousFetchedAt)
            expect(logic.values.blockRefresh).toBe(true)
        })

        it('refreshDashboardWidgets sets friendly error when run_widgets returns per-tile error', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const previousFetchedAt = logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.fetchedAt
            fetchRunWidgetsMock.mockResolvedValueOnce([
                {
                    tile_id: WIDGET_TILE.id,
                    widget_type: 'error_tracking_list',
                    result: null,
                    error: 'Query timeout',
                },
            ])

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
            }).toFinishAllListeners()

            expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.error).toBe(DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE)
            expect(logic.values.widgetResultsByTileId[WIDGET_TILE.id]?.error).toBe('Query timeout')
            expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.fetchedAt).toBe(previousFetchedAt)
        })

        it('refreshDashboardWidgets only marks failed tiles when a chunk has mixed results', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            fetchRunWidgetsMock.mockResolvedValueOnce([
                {
                    tile_id: 10,
                    widget_type: 'error_tracking_list',
                    result: { results: [], hasMore: false },
                    error: null,
                },
                {
                    tile_id: 11,
                    widget_type: 'session_replay_list',
                    result: null,
                    error: 'Query timeout',
                },
            ])

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [10, 11], forceRefresh: true })
            }).toFinishAllListeners()

            expect(logic.values.widgetRefreshStatus[10]?.error).toBeNull()
            expect(logic.values.widgetRefreshStatus[11]?.error).toBe(DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE)
        })

        it('duplicateTile refreshes newly duplicated widget tiles', async () => {
            const savedSm = { x: 0, y: 0, w: 4, h: 5 }
            const shiftedSm = { ...savedSm, y: 15 }
            dashboards[5].tiles[0] = {
                ...dashboards[5].tiles[0],
                layouts: { sm: savedSm } as DashboardTile['layouts'],
            }
            const duplicatedSm = { i: '99', x: 0, y: 10, w: 6, h: 5 }
            const duplicatedTile = {
                id: 99,
                widget: { id: '3', widget_type: 'error_tracking_list', config: { limit: 5 } },
                layouts: { sm: duplicatedSm },
                color: null,
            } as unknown as DashboardTile

            jest.spyOn(api, 'update').mockResolvedValueOnce(
                dashboardResult(5, [
                    { ...dashboards[5].tiles[0], layouts: { sm: shiftedSm } as DashboardTile['layouts'] },
                    ...dashboards[5].tiles.slice(1),
                    WIDGET_TILE,
                    duplicatedTile,
                ])
            )

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const firstTile = logic.values.dashboard!.tiles[0]
            const layouts = logic.values.layouts
            const changedX = (layouts.sm?.find((layout) => layout.i === String(firstTile.id))?.x ?? 0) + 1
            logic.actions.stageLayouts({
                ...layouts,
                sm: layouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: changedX } : layout
                ),
            })

            fetchRunWidgetsMock.mockResolvedValueOnce([
                {
                    tile_id: duplicatedTile.id,
                    widget_type: 'error_tracking_list',
                    result: { results: [{ id: 'issue-1' }], hasMore: false },
                    error: null,
                },
            ])

            await expectLogic(logic, () => {
                logic.actions.duplicateTile(WIDGET_TILE)
            })
                .toDispatchActions(['refreshDashboardWidgets'])
                .toFinishAllListeners()

            expect(fetchRunWidgetsMock).toHaveBeenCalledWith(
                String(MOCK_TEAM_ID),
                5,
                [duplicatedTile.id],
                expect.anything()
            )
            expect(logic.values.widgetResultsByTileId[duplicatedTile.id]?.result).toEqual({
                results: [{ id: 'issue-1' }],
                hasMore: false,
            })
            expect(logic.values.layouts.sm?.find((layout) => layout.i === String(firstTile.id))).toMatchObject(
                shiftedSm
            )
            expect(logic.values.layouts.sm?.find((layout) => layout.i === String(duplicatedTile.id))).toMatchObject(
                duplicatedSm
            )

            logic.actions.stageLayouts({
                ...logic.values.layouts,
                sm: logic.values.layouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: changedX } : layout
                ),
            })
            expect(logic.values.layouts.sm?.find((layout) => layout.i === String(firstTile.id))?.x).toBe(changedX)

            await expectLogic(logic, () => {
                logic.actions.saveLayoutChanges()
            }).toFinishAllListeners()
            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    tiles: expect.arrayContaining([
                        expect.objectContaining({
                            id: firstTile.id,
                            layouts: { sm: expect.objectContaining({ ...shiftedSm, x: changedX }) },
                        }),
                        expect.objectContaining({
                            id: duplicatedTile.id,
                            layouts: { sm: expect.objectContaining(duplicatedSm) },
                        }),
                    ]),
                })
            )
        })

        it('surfaces a failed tile duplicate instead of resolving it as a success', async () => {
            silenceKeaLoadersErrors()
            const errorToast = jest.spyOn(lemonToast, 'error')
            jest.spyOn(api, 'update').mockRejectedValueOnce(
                new ApiError('forbidden', 403, undefined, { detail: 'You do not have permission' })
            )

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.duplicateTile(WIDGET_TILE)
            })
                .toDispatchActions(['duplicateTileFailure'])
                .toFinishAllListeners()

            expect(errorToast).toHaveBeenCalledWith('You do not have permission')
            resumeKeaLoadersErrors()
        })

        it('addWidgetTiles refreshes newly created widget tiles', async () => {
            const addedTile = {
                id: 99,
                widget: { id: '3', widget_type: 'error_tracking_list', config: { limit: 5 } },
                layouts: { sm: { i: '99', x: 0, y: 10, w: 6, h: 5 } },
                color: null,
            } as unknown as DashboardTile

            jest.spyOn(api, 'create').mockResolvedValueOnce({
                tiles: [addedTile],
            })

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            fetchRunWidgetsMock.mockResolvedValueOnce([
                {
                    tile_id: addedTile.id,
                    widget_type: 'error_tracking_list',
                    result: { results: [], hasMore: false },
                    error: null,
                },
            ])

            await expectLogic(logic, () => {
                logic.actions.addWidgetTiles({
                    dashboardId: 5,
                    widgets: [{ widgetType: 'error_tracking_list', config: { limit: 5 } }],
                })
            })
                .toDispatchActions(['refreshDashboardWidgets'])
                .toFinishAllListeners()

            expect(fetchRunWidgetsMock).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 5, [addedTile.id], expect.anything())
        })

        it('addWidgetTiles keeps an existing tile movement unsaved', async () => {
            const addedTile = {
                id: 99,
                widget: { id: '3', widget_type: 'error_tracking_list', config: { limit: 5 } },
                layouts: { sm: { i: '99', x: 0, y: 10, w: 6, h: 5 } },
                color: null,
            } as unknown as DashboardTile
            jest.spyOn(api, 'create').mockResolvedValueOnce({ tiles: [addedTile] })

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const firstTile = logic.values.dashboard!.tiles[0]
            const savedLayouts = logic.values.savedTilePlacements[firstTile.id]?.layouts
            logic.actions.updateLayouts({
                ...logic.values.layouts,
                sm: logic.values.layouts.sm?.map((layout) =>
                    layout.i === String(firstTile.id) ? { ...layout, x: layout.x + 1 } : layout
                ),
            })
            const draftLayouts = logic.values.dashboard!.tiles[0].layouts
            expect(logic.values.hasUnsavedLayoutChanges).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.addWidgetTiles({
                    dashboardId: 5,
                    widgets: [{ widgetType: 'error_tracking_list', config: { limit: 5 } }],
                })
            }).toFinishAllListeners()

            expect(logic.values.dashboard!.tiles[0].layouts).toEqual(draftLayouts)
            expect(logic.values.savedTilePlacements[firstTile.id]?.layouts).toEqual(savedLayouts)
            expect(logic.values.savedTilePlacements[addedTile.id]?.layouts).toEqual(addedTile.layouts)
            expect(logic.values.hasUnsavedLayoutChanges).toBe(true)
        })

        it('updateWidgetTile persists config and metadata in one patch', async () => {
            const updateDashboardWidgetTileMock = jest
                .spyOn(dashboardWidgetUtils, 'updateDashboardWidgetTile')
                .mockResolvedValueOnce({
                    ...WIDGET_TILE,
                    widget: {
                        ...WIDGET_TILE.widget!,
                        name: 'Weekly errors',
                        description: 'Top issues this week',
                        config: { limit: 5 },
                    },
                } as DashboardTile)

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.updateWidgetTile({
                    tile: WIDGET_TILE,
                    config: { limit: 5 },
                    name: 'Weekly errors',
                    description: 'Top issues this week',
                })
            })
                .toDispatchActions(['refreshDashboardWidgets'])
                .toFinishAllListeners()

            expect(updateDashboardWidgetTileMock).toHaveBeenCalledWith({
                teamId: MOCK_TEAM_ID,
                dashboardId: 5,
                tile: WIDGET_TILE,
                config: { limit: 5 },
                name: 'Weekly errors',
                description: 'Top issues this week',
            })
            expect(logic.values.dashboard?.tiles.find((tile) => tile.id === WIDGET_TILE.id)?.widget).toMatchObject({
                name: 'Weekly errors',
                description: 'Top issues this week',
                config: { limit: 5 },
            })

            updateDashboardWidgetTileMock.mockRestore()
        })

        it('copyToDashboard calls copy_tile for widget tiles', async () => {
            jest.spyOn(api, 'create').mockResolvedValueOnce({})

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.copyToDashboard(WIDGET_TILE, 5, 8, 'Target dashboard')
            }).toFinishAllListeners()

            expect(api.create).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/dashboards/8/copy_tile`, {
                fromDashboardId: 5,
                tileId: WIDGET_TILE.id,
            })
        })
    })
})

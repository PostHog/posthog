// let tiles assert an insight is present in tests i.e. `tile!.insight` when it must be present for tests to pass
import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic, truth } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'
import * as dashboardWidgetUtils from '@posthog/products-dashboards/frontend/utils'
import { DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE } from '@posthog/products-dashboards/frontend/widgets/constants'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs, now } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import * as dashboardUtils from 'scenes/dashboard/dashboardUtils'
import * as widgetFetchUtils from 'scenes/dashboard/widgetFetchUtils'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { examples } from '~/queries/examples'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { HogQLVariable, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    DashboardMode,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightShortId,
    QueryBasedInsightModel,
} from '~/types'

import { dashboardResult, insightOnDashboard, tileFromInsight } from './dashboardLogic.testHelpers'

const TEXT_TILE: DashboardTile<QueryBasedInsightModel> = {
    id: 4,
    text: { body: 'I AM A TEXT', last_modified_at: '2021-01-01T00:00:00Z' },
    layouts: {},
    color: InsightColor.Blue,
}

const WIDGET_TILE: DashboardTile<QueryBasedInsightModel> = {
    id: 7,
    widget: { id: '1', widget_type: 'error_tracking_list', config: {} },
    layouts: {},
    color: null,
}

const WIDGET_TILE_WITH_CUSTOM_NAME: DashboardTile<QueryBasedInsightModel> = {
    id: 8,
    widget: { id: '2', widget_type: 'error_tracking_list', config: {}, name: 'Critical errors' },
    layouts: {},
    color: null,
}

const uncached = (insight: QueryBasedInsightModel): QueryBasedInsightModel => ({
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
                '/api/environments/:team_id/dashboards/5/': { ...dashboards[5] },
                '/api/environments/:team_id/dashboards/6/': { ...dashboards[6] },
                '/api/environments/:team_id/dashboards/7/': () => [500, '💣'],
                '/api/environments/:team_id/dashboards/8/': { ...dashboards[8] },
                '/api/environments/:team_id/dashboards/9/': { ...dashboards[9] },
                '/api/environments/:team_id/dashboards/10/': { ...dashboards[10] },
                '/api/environments/:team_id/dashboards/11/': { ...dashboards[11] },
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
                '/api/environments/:team_id/insights/:id/': async ({ request, params }) => {
                    try {
                        const updates = await request.json()
                        if (typeof updates !== 'object') {
                            return [500, `this update should receive an object body not ${JSON.stringify(updates)}`]
                        }
                        const insightId = boxToId(params.id as string | readonly string[])

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

    describe('key() guard', () => {
        it.each([
            ['NaN', NaN],
            ['undefined', undefined as unknown as number],
            ['Infinity', Infinity],
        ])('throws when id is %s', (_label, id) => {
            expect(() => dashboardLogic({ id })).toThrow(/non-finite id/)
        })

        it('accepts a finite numeric id', () => {
            expect(() => dashboardLogic({ id: 42 })).not.toThrow()
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

        it('saving without changes does not call api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
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
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/environments/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    tiles: expect.any(Array),
                })
            )
        })

        it('saving after filter change calls api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/environments/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    filters: expect.objectContaining({ date_from: '-7d' }),
                })
            )
        })

        it('dashboard save after changing global dates runs tile refresh to repopulate insight results missing from PATCH', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setDates('-7d', null)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            })
                .toDispatchActions(['saveEditModeChanges', 'saveEditModeChangesSuccess', 'refreshDashboardItems'])
                .toFinishAllListeners()
        })

        it('saving after breakdown color change calls api', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setBreakdownColorConfig({ breakdownValue: 'x', color: 'red' } as any)
            }).toFinishAllListeners()

            jest.spyOn(api, 'update')

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/environments/${MOCK_TEAM_ID}/dashboards/5`,
                expect.objectContaining({
                    breakdown_colors: expect.any(Array),
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
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(api.update).toHaveBeenCalledWith(
                `api/environments/${MOCK_TEAM_ID}/dashboards/5`,
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
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(successToast).toHaveBeenCalledWith('Dashboard saved')
        })

        it('does not show a success toast when exiting edit mode with no changes', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const successToast = jest.spyOn(lemonToast, 'success')

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            }).toFinishAllListeners()

            expect(successToast).not.toHaveBeenCalled()
        })

        it('discarding edit mode restores original layouts', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const initialDashboard = logic.values.dashboard
            expect(initialDashboard).not.toBeNull()

            const firstTile = initialDashboard!.tiles[0]
            const originalLayouts = logic.values.dashboardLayouts[firstTile.id]

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
                logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }).toFinishAllListeners()

            const restoredTileLayouts = logic.values.dashboard?.tiles.find((t) => t.id === firstTile.id)?.layouts
            expect(restoredTileLayouts).toEqual(originalLayouts)
        })

        it('discarding a layout-only edit does not refetch tile data', async () => {
            await expectLogic(logic).toFinishAllListeners()

            // Enter layout edit mode so the pre-edit URL snapshot is captured
            await expectLogic(logic, () => {
                logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
            }).toFinishAllListeners()

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

            const refreshSpy = jest.spyOn(logic.actions, 'refreshDashboardItems')

            await expectLogic(logic, () => {
                logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }).toFinishAllListeners()

            expect(refreshSpy).not.toHaveBeenCalled()

            // the saved layout is still restored without the refetch
            const restoredTileLayouts = logic.values.dashboard?.tiles.find((t) => t.id === firstTile.id)?.layouts
            expect(restoredTileLayouts).toEqual(logic.values.dashboardLayouts[firstTile.id])

            refreshSpy.mockRestore()
        })

        it('discarding after a filter preview still refetches tile data', async () => {
            await expectLogic(logic).toFinishAllListeners()

            // Enter layout edit mode so the pre-edit URL snapshot is captured
            await expectLogic(logic, () => {
                logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
            }).toFinishAllListeners()

            // Previewing a global date change writes the new filter to the URL, so on discard the
            // tile data genuinely needs reverting and a refetch is expected.
            await expectLogic(logic, () => {
                logic.actions.setDates('-30d', null)
            }).toFinishAllListeners()

            const refreshSpy = jest.spyOn(logic.actions, 'refreshDashboardItems')

            await expectLogic(logic, () => {
                logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }).toFinishAllListeners()

            expect(refreshSpy).toHaveBeenCalled()

            refreshSpy.mockRestore()
        })

        describe('layoutEditMode', () => {
            it('enters edit mode without layout editing when filters change', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        dashboardMode: DashboardMode.Edit,
                        layoutEditMode: false,
                    })
            })

            it('enables layout editing for explicit layout edit sources', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        dashboardMode: DashboardMode.Edit,
                        layoutEditMode: true,
                    })
            })

            it('clears layout editing when exiting edit mode', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
                }).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        dashboardMode: null,
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
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
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
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
                }).toFinishAllListeners()

                expect(reportLayoutEditEntered).toHaveBeenCalledWith(
                    expect.objectContaining({ id: 5 }),
                    DashboardEventSource.SceneCommonButtons,
                    1
                )
                expect(reportModeToggled).toHaveBeenCalledWith(
                    expect.objectContaining({ id: 5 }),
                    DashboardMode.Edit,
                    DashboardEventSource.SceneCommonButtons,
                    1,
                    true
                )
                expect(reportFiltersChanged).not.toHaveBeenCalled()

                reportFiltersChanged.mockRestore()
                reportLayoutEditEntered.mockRestore()
                reportModeToggled.mockRestore()
            })

            it('restoreUrlStateAtEditModeEntry applies snapshot payload to url', async () => {
                const editedFilters = JSON.stringify({ date_from: '-14d', date_to: null })
                const originalFilters = JSON.stringify({ date_from: '-7d', date_to: null })

                logic.unmount()
                router.actions.push('/dashboard/5', {
                    [dashboardUtils.SEARCH_PARAM_FILTERS_KEY]: editedFilters,
                })
                logic = dashboardLogic({ id: 5 })
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.restoreUrlStateAtEditModeEntry({
                        filters: originalFilters,
                        variables: undefined,
                    })
                }).toFinishAllListeners()

                expect(router.values.searchParams[dashboardUtils.SEARCH_PARAM_FILTERS_KEY]).toBe(originalFilters)
            })

            it('discarding filter edit passes url snapshot into restore action', async () => {
                const originalFilters = JSON.stringify({ date_from: '-7d', date_to: null })

                logic.unmount()
                router.actions.push('/dashboard/5', {
                    [dashboardUtils.SEARCH_PARAM_FILTERS_KEY]: originalFilters,
                })
                logic = dashboardLogic({ id: 5 })
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.urlFilters).toEqual(expect.objectContaining({ date_from: '-7d' }))
                expect(logic.values.urlSearchParamsAtEditModeEntry).toBeNull()

                const restoreSpy = jest.spyOn(logic.actions, 'restoreUrlStateAtEditModeEntry')

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        urlSearchParamsAtEditModeEntry: {
                            filters: originalFilters,
                            variables: undefined,
                        },
                    })

                await expectLogic(logic, () => {
                    logic.actions.setDates('-14d', null)
                }).toFinishAllListeners()

                restoreSpy.mockClear()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                }).toFinishAllListeners()

                expect(restoreSpy).toHaveBeenCalledWith({
                    filters: originalFilters,
                    variables: undefined,
                })

                restoreSpy.mockRestore()
            })

            it('filter edit source clears layout edit mode', async () => {
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.SceneCommonButtons)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        layoutEditMode: true,
                    })

                await expectLogic(logic, () => {
                    logic.actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        layoutEditMode: false,
                    })
            })
        })

        describe('hasUnsavedLayoutChanges selector', () => {
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
                    logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
                })
                    .toFinishAllListeners()
                    .toMatchValues({ hasUnsavedLayoutChanges: false })
            })
        })

        describe('cancelEditMode action', () => {
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
                    logic.actions.cancelEditMode()
                }).toDispatchActions([
                    logic.actionCreators.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges),
                ])
            })

            it('does not exit edit mode when a tile has been moved and the prompt flag is on', async () => {
                setDiscardPromptFlag(true)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, moveFirstTile).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.cancelEditMode()
                }).toNotHaveDispatchedActions([
                    logic.actionCreators.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges),
                ])
            })

            it('exits edit mode immediately when the prompt flag is off, even with unsaved layout changes', async () => {
                setDiscardPromptFlag(false)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, moveFirstTile).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.cancelEditMode()
                }).toDispatchActions([
                    logic.actionCreators.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges),
                ])
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
                `api/environments/${MOCK_TEAM_ID}/dashboards/${9}/move_tile`,
                expect.objectContaining({ tile: sourceTile, to_dashboard: 8 })
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

                    // forceRefresh: true so every insight tile hits getInsightWithRetry (applyFilters/preview can skip fresh tiles)
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
                    logic.actions.saveEditModeChanges()

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
                    logic.actions.setAutoRefresh(true, 1800)
                })
                    .toDispatchActions(['setAutoRefresh', 'resetInterval'])
                    .toMatchValues({
                        autoRefresh: { enabled: true, interval: 1800 },
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
        }: {
            urlValue?: string | null
            dashboardOverride?: Partial<HogQLVariable>
            insightOverride?: Partial<HogQLVariable>
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
                ...dashboardResult(12, [tileFromInsight(insightWithVariable)]),
                persisted_variables: dashboardOverride
                    ? {
                          [variableId]: {
                              ...baseVariable,
                              ...dashboardOverride,
                          },
                      }
                    : undefined,
            }

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

        it('dashboard save after variable-only edits runs tile refresh to repopulate insight results missing from PATCH', async () => {
            await mountDashboardWithVariable({
                urlValue: 'url-override',
                dashboardOverride: { value: 'persisted', isNull: false },
            })

            await expectLogic(logic, () => {
                logic.actions.saveEditModeChanges()
            })
                .toDispatchActions(['saveEditModeChanges', 'saveEditModeChangesSuccess', 'refreshDashboardItems'])
                .toFinishAllListeners()
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
                } as QueryBasedInsightModel)
            })
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboard'])
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

        it('removes the tile from state optimistically before the API call resolves', () => {
            expect(logic.values.textTiles).toHaveLength(1)

            // Dispatch without awaiting listeners — the reducer drops the tile synchronously.
            logic.actions.removeTile(TEXT_TILE)

            expect(logic.values.textTiles).toEqual([])
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
        })

        it('resets layoutZoom to 1 when leaving edit mode', async () => {
            await expectLogic(logic, () => {
                logic.actions.setLayoutZoom(0.5)
            }).toMatchValues({ layoutZoom: 0.5 })

            await expectLogic(logic, () => {
                logic.actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderSaveDashboard)
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

    describe('widget orchestration', () => {
        let fetchRunWidgetsMock: jest.SpiedFunction<typeof widgetFetchUtils.fetchRunWidgets>

        beforeEach(() => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_WIDGETS], {
                [FEATURE_FLAGS.DASHBOARD_WIDGETS]: true,
            })
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
                } as DashboardType<QueryBasedInsightModel>,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(fetchRunWidgetsMock).not.toHaveBeenCalled()

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
            }).toFinishAllListeners()

            expect(fetchRunWidgetsMock).not.toHaveBeenCalled()
        })

        it('enables widget tiles on public dashboards when tile metadata is present', async () => {
            logic = dashboardLogic({
                id: 5,
                placement: DashboardPlacement.Public,
                dashboard: {
                    ...dashboards[5],
                    tiles: [...dashboards[5].tiles, WIDGET_TILE],
                } as DashboardType<QueryBasedInsightModel>,
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dashboardWidgetsEnabled).toBe(true)
        })

        it('refreshDashboardWidgets sets friendly error when run_widgets fails', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            fetchRunWidgetsMock.mockRejectedValueOnce(new Error('Network error'))

            await expectLogic(logic, () => {
                logic.actions.refreshDashboardWidgets({ tileIds: [WIDGET_TILE.id], forceRefresh: true })
            }).toFinishAllListeners()

            expect(logic.values.widgetRefreshStatus[WIDGET_TILE.id]?.error).toBe(DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE)
        })

        it('refreshDashboardWidgets sets friendly error when run_widgets returns per-tile error', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

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
            const duplicatedTile = {
                id: 99,
                widget: { id: '3', widget_type: 'error_tracking_list', config: { limit: 5 } },
                layouts: { sm: { i: '99', x: 0, y: 10, w: 6, h: 5 } },
                color: null,
            } as unknown as DashboardTile<QueryBasedInsightModel>

            jest.spyOn(api, 'update').mockResolvedValueOnce(
                dashboardResult(5, [...dashboards[5].tiles, WIDGET_TILE, duplicatedTile])
            )

            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

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
        })

        it('addWidgetTiles refreshes newly created widget tiles', async () => {
            const addedTile = {
                id: 99,
                widget: { id: '3', widget_type: 'error_tracking_list', config: { limit: 5 } },
                layouts: { sm: { i: '99', x: 0, y: 10, w: 6, h: 5 } },
                color: null,
            } as unknown as DashboardTile<QueryBasedInsightModel>

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
                } as DashboardTile<QueryBasedInsightModel>)

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

            expect(api.create).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}/dashboards/8/copy_tile`, {
                fromDashboardId: 5,
                tileId: WIDGET_TILE.id,
            })
        })
    })
})

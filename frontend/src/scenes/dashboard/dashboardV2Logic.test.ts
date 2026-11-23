import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic, RefreshDashboardItemsAction } from 'scenes/dashboard/dashboardLogic'
import * as dashboardUtils from 'scenes/dashboard/dashboardUtils'
import { dashboardV2Logic } from 'scenes/dashboard/dashboardV2Logic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { DashboardTile, InsightShortId } from '~/types'

import { dashboardResult, insightOnDashboard, tileFromInsight } from './dashboardLogic.testHelpers'

describe('dashboardV2Logic', () => {
    let logic: ReturnType<typeof dashboardLogic.build>
    let refreshInsight: jest.SpiedFunction<typeof dashboardUtils.getInsightWithRetry>
    let boardStream: jest.SpiedFunction<typeof api.stream>
    const tiles = Array.from({ length: 15 }, (_, index) =>
        tileFromInsight(
            {
                ...insightOnDashboard(175, [21]),
                id: 900 + index,
                short_id: `long-${index}` as InsightShortId,
                cache_target_age: undefined,
            },
            9000 + index
        )
    )
    const v2Logic = (): ReturnType<typeof dashboardV2Logic.build> => dashboardV2Logic({ id: 21 })
    const loadedShortIds = (): string[] => refreshInsight.mock.calls.map((call) => call[1].short_id)
    const setDashboardV2 = (enabled: boolean): void => {
        const flags = enabled ? [FEATURE_FLAGS.DASHBOARD_V2, FEATURE_FLAGS.DASHBOARD_V2_USERS] : []
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }
    const autoRefresh = async (): Promise<void> => {
        await expectLogic(logic, () => {
            logic.actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Refresh,
                forceRefresh: true,
                isAutomatic: true,
            })
        }).toFinishAllListeners()
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/21/': () => [200, dashboardResult(21, tiles)],
            },
            post: {
                '/api/environments/:team_id/insights/cancel/': [201],
            },
        })
        initKeaTests()
        dashboardsModel.mount()
        insightsModel.mount()
        refreshInsight = jest
            .spyOn(dashboardUtils, 'getInsightWithRetry')
            .mockImplementation((_teamId, insight) => Promise.resolve(insight))
        // Without a board stream, dashboard-v2 loads each tile on its own, so the deferral rules below hold either way.
        boardStream = jest.spyOn(api, 'stream').mockRejectedValue(new Error('stream unavailable'))
    })

    afterEach(() => {
        refreshInsight.mockRestore()
        boardStream.mockRestore()
        setDashboardV2(false)
    })

    it('queries the first screen up front and each later tile once it scrolls into view', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(tiles.slice(0, 12).map((tile) => tile.insight!.short_id))

        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[13].id, true)
            v2Logic().actions.setTileInView(tiles[0].id, true)
            v2Logic().actions.setTileInView(tiles[13].id, true)
        }).toFinishAllListeners()

        expect(loadedShortIds().slice(12)).toEqual(['long-13'])
        expect(refreshInsight.mock.calls[12][4]).toEqual('blocking')
        expect(logic.values.refreshStatus['long-0']).toMatchObject({ refreshed: true })
        expect(v2Logic().values.deferredTileIds).toEqual([tiles[12].id, tiles[14].id])
    })

    it('loads a tile past the first screen that was already in view when the first load started', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        v2Logic().actions.setTileInView(tiles[13].id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(loadedShortIds()).toContain('long-13')
        expect(v2Logic().values.deferredTileIds).toEqual([tiles[12].id, tiles[14].id])
    })

    it('loads a deferred tile with the filters of the load that skipped it', async () => {
        setDashboardV2(true)
        router.actions.push(urls.dashboard(21), { query_filters: JSON.stringify({ date_from: '-3d' }) })
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        refreshInsight.mockClear()

        await expectLogic(logic, () => {
            logic.actions.setInitialDashboardSettingsOverride({ filters: { date_from: '-30d' }, variables: {} })
            v2Logic().actions.setTileInView(tiles[13].id, true)
        }).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(['long-13'])
        expect(refreshInsight.mock.calls[0][6]).toMatchObject({ date_from: '-3d' })
    })

    it('auto refresh queries the tiles in view and refreshes a hidden tile once it scrolls back in', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[0].id, true)
            v2Logic().actions.setTileInView(tiles[1].id, true)
        }).toFinishAllListeners()
        refreshInsight.mockClear()

        await autoRefresh()

        expect(loadedShortIds()).toEqual(['long-0', 'long-1'])

        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[1].id, false)
            v2Logic().actions.setTileInView(tiles[7].id, true)
        }).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(['long-0', 'long-1', 'long-7'])
        expect(refreshInsight.mock.calls.map((call) => call[4])).toEqual([
            'force_blocking',
            'force_blocking',
            'force_blocking',
        ])

        // Scrolled to a region with no insights: an automatic refresh queries none.
        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[0].id, false)
            v2Logic().actions.setTileInView(tiles[7].id, false)
        }).toFinishAllListeners()
        refreshInsight.mockClear()

        await autoRefresh()

        expect(loadedShortIds()).toEqual([])
    })

    const storedMetric = { kind: NodeKind.MetricsQuery, clauses: [{ metricName: 'http.requests' }] }
    const derivedMetric = { kind: NodeKind.MetricsQuery, clauses: [{ metricName: 'posthog.derived.spans.requests' }] }

    it.each([
        // 6 metrics tiles fill the metrics queue, and the analytics tile still starts
        { name: 'metrics', query: storedMetric, requestsStarted: 7, analyticsTileStarts: true },
        // The server runs these in the analytics slots, so they share the analytics queue
        { name: 'derived metrics', query: derivedMetric, requestsStarted: 4, analyticsTileStarts: false },
        {
            name: 'histogram',
            query: { kind: NodeKind.MetricsHistogramQuery },
            requestsStarted: 4,
            analyticsTileStarts: false,
        },
    ])(
        'with dashboard-v2, an analytics tile starts while $name tiles fill their queue: $analyticsTileStarts',
        async ({ query, requestsStarted, analyticsTileStarts }) => {
            setDashboardV2(true)
            const metricsTiles = tiles.slice(0, 8).map((tile) => ({
                ...tile,
                insight: { ...tile.insight!, query: query as any },
            }))
            const analyticsTile = tiles[8]
            useMocks({
                get: {
                    '/api/environments/:team_id/dashboards/21/': () => [
                        200,
                        dashboardResult(21, [...metricsTiles, analyticsTile]),
                    ],
                },
            })
            refreshInsight.mockImplementation((_teamId, insight) =>
                insight.query?.kind === query.kind ? new Promise(() => {}) : Promise.resolve(insight)
            )
            logic = dashboardLogic({ id: 21 })
            logic.mount()

            await waitFor(() => expect(refreshInsight).toHaveBeenCalledTimes(requestsStarted))
            expect(loadedShortIds().includes(analyticsTile.insight!.short_id)).toBe(analyticsTileStarts)
        }
    )

    it('a manual refresh queries every tile, even with dashboard-v2', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        v2Logic().actions.setTileInView(tiles[0].id, true)
        refreshInsight.mockClear()

        await expectLogic(logic, () => {
            logic.actions.triggerDashboardRefresh()
        }).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(tiles.map((tile) => tile.insight!.short_id))
        expect(v2Logic().values.deferredTileIds).toEqual([])
    })

    describe('board stream', () => {
        const streamBoard = (
            run: (send: (event: Record<string, unknown>) => void, params: URLSearchParams) => Promise<void>
        ): void => {
            boardStream.mockImplementation(async (url, options) => {
                await run(
                    (event) => options.onMessage({ id: '', event: '', data: JSON.stringify(event) }),
                    new URL(url, 'http://localhost').searchParams
                )
            })
        }
        const resultOf = (tileId: number): unknown =>
            logic.values.insightTiles.find((tile) => tile.id === tileId)?.insight?.result
        const computedTile = (tile: DashboardTile, insight: Record<string, unknown> = {}): Record<string, unknown> => ({
            type: 'tile',
            tile: {
                ...tile,
                insight: { ...tile.insight, result: ['computed'], query_status: { complete: true }, ...insight },
            },
        })
        const firstScreen = tiles.slice(0, 12)
        const capturedEvents = (capture: jest.SpyInstance, name: string): Record<string, any>[] =>
            capture.mock.calls.filter(([event]) => event === name).map(([, properties]) => properties)

        it('paints every cached result at once, stale ones too, and replaces them as tiles finish', async () => {
            setDashboardV2(true)
            let release!: () => void
            const blocked = new Promise<void>((resolve) => {
                release = resolve
            })
            let cachedSent!: () => void
            const painted = new Promise<void>((resolve) => {
                cachedSent = resolve
            })
            let requested: URLSearchParams | undefined
            streamBoard(async (send, params) => {
                requested = params
                send({
                    type: 'cached',
                    tiles: [
                        { id: firstScreen[0].id, status: 'hit', stale: true, insight: { result: ['stale'] } },
                        { id: firstScreen[1].id, status: 'hit', stale: false, insight: { result: ['fresh'] } },
                        ...firstScreen.slice(2).map((tile) => ({ id: tile.id, status: 'miss' })),
                    ],
                    pending: [firstScreen[0].id, ...firstScreen.slice(2).map((tile) => tile.id)],
                })
                cachedSent()
                await blocked
                for (const tile of [firstScreen[0], ...firstScreen.slice(2)]) {
                    send(computedTile(tile))
                }
                send({ type: 'complete' })
            })

            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await painted

            expect(resultOf(firstScreen[0].id)).toEqual(['stale'])
            expect(resultOf(firstScreen[1].id)).toEqual(['fresh'])
            expect(logic.values.refreshStatus[firstScreen[0].insight!.short_id]).toMatchObject({ queued: true })
            expect(logic.values.refreshStatus[firstScreen[1].insight!.short_id]).toMatchObject({ refreshed: true })

            release()
            await expectLogic(logic).toFinishAllListeners()

            expect(resultOf(firstScreen[0].id)).toEqual(['computed'])
            expect(resultOf(firstScreen[11].id)).toEqual(['computed'])
            expect(logic.values.refreshStatus[firstScreen[0].insight!.short_id]).toMatchObject({ refreshed: true })
            expect(refreshInsight).not.toHaveBeenCalled()
            expect(boardStream).toHaveBeenCalledTimes(1)
            expect(requested?.get('tile_ids')).toEqual(firstScreen.map((tile) => tile.id).join(','))
            expect(requested?.get('cached_first')).toEqual('true')
            expect(requested?.get('refresh')).toEqual('blocking')
            expect(v2Logic().values.deferredTileIds).toEqual(tiles.slice(12).map((tile) => tile.id))
        })

        it('falls back to one request per tile for the tiles a failed stream did not deliver, and says so', async () => {
            setDashboardV2(true)
            const capture = jest.spyOn(posthog, 'capture').mockClear()
            streamBoard(async (send) => {
                send({
                    type: 'cached',
                    tiles: [
                        { id: firstScreen[0].id, status: 'hit', stale: false, insight: { result: ['fresh'] } },
                        ...firstScreen.slice(1).map((tile) => ({ id: tile.id, status: 'miss' })),
                    ],
                    pending: firstScreen.slice(1).map((tile) => tile.id),
                })
                send(computedTile(firstScreen[1]))
                throw new Error('stream disconnected')
            })

            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(loadedShortIds()).toEqual(firstScreen.slice(2).map((tile) => tile.insight!.short_id))
            expect(refreshInsight.mock.calls.map((call) => call[9])).toEqual(firstScreen.slice(2).map(() => 1))
            expect(resultOf(firstScreen[0].id)).toEqual(['fresh'])
            expect(resultOf(firstScreen[1].id)).toEqual(['computed'])
            const tileEvents = capturedEvents(capture, 'dashboard insight refreshed')
            expect(
                Object.fromEntries(tileEvents.map((event) => [event.insight_short_id, event.stream_fallback]))
            ).toEqual(Object.fromEntries(firstScreen.map((tile, index) => [tile.insight!.short_id, index >= 2])))
            expect(capturedEvents(capture, 'dashboard refreshed')).toEqual([
                expect.objectContaining({ board_stream: true, stream_fallback: true, stream_failed: true }),
            ])
        })

        it('leaves a tile the organization had no capacity for to the per-tile path', async () => {
            setDashboardV2(true)
            streamBoard(async (send) => {
                send({ type: 'cached', tiles: [], pending: firstScreen.map((tile) => tile.id) })
                send(computedTile(firstScreen[0], { query_status: { error: true, error_code: 'rate_limited' } }))
                firstScreen.slice(1).forEach((tile) => send(computedTile(tile)))
                send({ type: 'complete' })
            })

            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(loadedShortIds()).toEqual([firstScreen[0].insight!.short_id])
            expect(refreshInsight.mock.calls[0][9]).toEqual(1)
            expect(resultOf(firstScreen[1].id)).toEqual(['computed'])
        })

        it('a manual refresh streams every tile with a recompute', async () => {
            setDashboardV2(true)
            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const requests: URLSearchParams[] = []
            streamBoard(async (send, params) => {
                requests.push(params)
                send({ type: 'cached', tiles: [], pending: tiles.map((tile) => tile.id) })
                tiles.forEach((tile) => send(computedTile(tile)))
                send({ type: 'complete' })
            })
            refreshInsight.mockClear()

            await expectLogic(logic, () => {
                logic.actions.triggerDashboardRefresh()
            }).toFinishAllListeners()

            expect(requests.map((params) => [params.get('refresh'), params.get('tile_ids')])).toEqual([
                ['force_blocking', tiles.map((tile) => tile.id).join(',')],
            ])
            expect(refreshInsight).not.toHaveBeenCalled()
        })

        it('without dashboard-v2, loads each tile on its own and reports no stream', async () => {
            setDashboardV2(false)
            const capture = jest.spyOn(posthog, 'capture').mockClear()

            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(boardStream).not.toHaveBeenCalled()
            expect(loadedShortIds()).toEqual(tiles.map((tile) => tile.insight!.short_id))
            expect(refreshInsight.mock.calls.map((call) => call[9])).toEqual(tiles.map(() => undefined))
            for (const name of ['dashboard refreshed', 'dashboard insight refreshed']) {
                for (const properties of capturedEvents(capture, name)) {
                    expect(properties).not.toHaveProperty('stream_fallback')
                    expect(properties).not.toHaveProperty('board_stream')
                }
            }
        })

        it('a first load reads tile metadata only, then one stream paints the first screen', async () => {
            setDashboardV2(true)
            const dashboardGets: URLSearchParams[] = []
            useMocks({
                get: {
                    '/api/environments/:team_id/dashboards/21/': ({ request }) => {
                        dashboardGets.push(new URL(request.url).searchParams)
                        return [200, dashboardResult(21, tiles)]
                    },
                },
            })
            const streams: URLSearchParams[] = []
            streamBoard(async (send, params) => {
                streams.push(params)
                const ids = params.get('tile_ids')!.split(',').map(Number)
                send({
                    type: 'cached',
                    tiles: ids.map((id) => ({ id, status: 'hit', stale: false, insight: { result: ['cached'] } })),
                    pending: [],
                })
                send({ type: 'complete' })
            })

            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(dashboardGets.map((params) => params.get('omit_tile_results'))).toEqual(['true'])
            expect(streams.map((params) => params.get('tile_ids'))).toEqual([
                firstScreen.map((tile) => tile.id).join(','),
            ])
            expect(refreshInsight).not.toHaveBeenCalled()
            expect(resultOf(firstScreen[11].id)).toEqual(['cached'])
        })

        it('tiles that scroll into view together load through one more stream', async () => {
            setDashboardV2(true)
            const streams: URLSearchParams[] = []
            streamBoard(async (send, params) => {
                streams.push(params)
                const ids = params.get('tile_ids')!.split(',').map(Number)
                send({ type: 'cached', tiles: [], pending: ids })
                ids.forEach((id) => send(computedTile(tiles.find((tile) => tile.id === id)!)))
                send({ type: 'complete' })
            })
            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            streams.length = 0

            await expectLogic(logic, () => {
                v2Logic().actions.setTileInView(tiles[12].id, true)
                v2Logic().actions.setTileInView(tiles[13].id, true)
                v2Logic().actions.setTileInView(tiles[14].id, true)
            }).toFinishAllListeners()

            expect(logic.values.refreshStatus[tiles[14].insight!.short_id]).toMatchObject({ refreshed: true })
            expect(streams.map((params) => params.get('tile_ids'))).toEqual([
                tiles
                    .slice(12)
                    .map((tile) => tile.id)
                    .join(','),
            ])
            expect(refreshInsight).not.toHaveBeenCalled()
            expect(resultOf(tiles[13].id)).toEqual(['computed'])
        })

        it('a scrolled-in batch whose stream fails loads one request per tile', async () => {
            setDashboardV2(true)
            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            refreshInsight.mockClear()

            await expectLogic(logic, () => {
                v2Logic().actions.setTileInView(tiles[12].id, true)
                v2Logic().actions.setTileInView(tiles[13].id, true)
            }).toFinishAllListeners()

            expect(
                boardStream.mock.calls.map(([url]) => new URL(url, 'http://localhost').searchParams.get('tile_ids'))
            ).toEqual([firstScreen.map((tile) => tile.id).join(','), `${tiles[12].id},${tiles[13].id}`])
            expect(loadedShortIds()).toEqual(['long-12', 'long-13'])
            expect(refreshInsight.mock.calls.map((call) => call[9])).toEqual([1, 1])
        })

        it('a scrolled-in batch cancelled during its debounce starts no stream', async () => {
            setDashboardV2(true)
            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            boardStream.mockClear()

            await expectLogic(logic, () => {
                v2Logic().actions.setTileInView(tiles[12].id, true)
                v2Logic().actions.setTileInView(tiles[13].id, true)
                logic.actions.cancelDashboardRefresh()
            }).toFinishAllListeners()

            expect(boardStream).not.toHaveBeenCalled()
        })

        it('without dashboard-v2, the dashboard GET carries every tile result', async () => {
            setDashboardV2(false)
            const dashboardGets: URLSearchParams[] = []
            useMocks({
                get: {
                    '/api/environments/:team_id/dashboards/21/': ({ request }) => {
                        dashboardGets.push(new URL(request.url).searchParams)
                        return [200, dashboardResult(21, tiles)]
                    },
                },
            })

            logic = dashboardLogic({ id: 21 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(dashboardGets.map((params) => params.has('omit_tile_results'))).toEqual([false])
        })
    })
})

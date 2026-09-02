import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'

import {
    DASHBOARD_AI_HIGHLIGHT_MS,
    DashboardAiPendingChange,
    DashboardTileIdentity,
    dashboardAiSyncLogic,
    dashboardToolTargetsCurrentDashboard,
    resolveHighlightedTileIds,
} from './dashboardAiSyncLogic'
import { dashboardResult } from './dashboardLogic.testHelpers'

const deferred = <T>(): {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (reason?: unknown) => void
} => {
    let resolve!: (value: T) => void
    let reject!: (reason?: unknown) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

const dashboardTile = (id: number, insight?: { id: number; short_id: string }): DashboardTile<QueryBasedInsightModel> =>
    ({
        id,
        layouts: {},
        insight: insight ? { ...insight, saved: true, query: null } : null,
    }) as DashboardTile<QueryBasedInsightModel>

const dashboardResponse = (dashboardId: number, tiles: DashboardTile<QueryBasedInsightModel>[]): Response =>
    new Response(JSON.stringify(dashboardResult(dashboardId, tiles)), {
        headers: { 'Content-Type': 'application/json' },
    })

const dashboardRequests = (getResponse: jest.SpyInstance, dashboardId: number): unknown[][] =>
    getResponse.mock.calls.filter(([url]) => String(url).includes(`/dashboards/${dashboardId}/`))

const mockDashboardResponses = (dashboardId: number, ...responses: Promise<Response>[]): jest.SpyInstance => {
    const originalGetResponse = api.getResponse
    const responseQueue = [...responses]
    return jest.spyOn(api, 'getResponse').mockImplementation((url, options) => {
        if (String(url).includes(`/dashboards/${dashboardId}/`)) {
            const response = responseQueue.shift()
            if (!response) {
                throw new Error(`Unexpected dashboard ${dashboardId} response request`)
            }
            return response
        }
        return originalGetResponse(url, options)
    })
}

describe('dashboardAiSyncLogic', () => {
    let logic: ReturnType<typeof dashboardAiSyncLogic.build>
    let dashboardSceneLogic: ReturnType<typeof dashboardLogic.build>
    let subscriptionsListSpy: jest.SpyInstance
    let alertsListSpy: jest.SpyInstance

    const baselineTiles: DashboardTileIdentity[] = [
        { tileId: 10, insightId: 42, insightShortId: 'abc123' },
        { tileId: 11 },
    ]

    beforeEach(() => {
        jest.useFakeTimers()
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/5/': dashboardResult(5, []),
            },
        })
        initKeaTests()
        subscriptionsListSpy = jest.spyOn(api.subscriptions, 'list').mockResolvedValue({ results: [] })
        alertsListSpy = jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [], count: 0 })
        dashboardSceneLogic = dashboardLogic({
            id: 5,
            dashboard: dashboardResult(5, []),
        })
        dashboardSceneLogic.mount()
        logic = dashboardAiSyncLogic({ dashboardId: 5 })
        logic.mount()
        silenceKeaLoadersErrors()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic.unmount()
        dashboardSceneLogic.unmount()
        subscriptionsListSpy.mockRestore()
        alertsListSpy.mockRestore()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each([
        ['dashboard-update', { id: 5 }, true],
        ['dashboard-create-text-tile', { id: '5' }, true],
        ['dashboard-widgets-batch-update', { id: 8 }, false],
        ['dashboards-move-tile-partial-update', { id: 5, to_dashboard: 8 }, true],
        ['dashboards-move-tile-partial-update', { id: 8, to_dashboard: 5 }, true],
        ['insight-update', { id: 42 }, true],
        ['insight-update', { id: 99 }, false],
        ['insight-create', { dashboards: [5] }, true],
        ['insight-delete', { id: 'abc123' }, true],
    ])('%s targets the current dashboard when expected', (toolName, innerInput, expected) => {
        expect(dashboardToolTargetsCurrentDashboard(toolName, innerInput, 5, baselineTiles)).toBe(expected)
    })

    describe.each(['insight-update', 'insight-delete'])('%s identifier aliases', (toolName) => {
        test.each(['id', 'insightId', 'insight_id', 'short_id', 'shortId'])(
            'reloads only the dashboard containing the insight for %s',
            async (alias) => {
                const unrelatedDashboardLogic = dashboardLogic({
                    id: 6,
                    dashboard: dashboardResult(6, []),
                })
                const unrelatedSyncLogic = dashboardAiSyncLogic({ dashboardId: 6 })
                unrelatedDashboardLogic.mount()
                unrelatedSyncLogic.mount()
                const getResponse = mockDashboardResponses(5, Promise.resolve(dashboardResponse(5, [])))

                try {
                    logic.actions.agentToolCompleted(toolName, { [alias]: 'abc123' }, baselineTiles)
                    unrelatedSyncLogic.actions.agentToolCompleted(toolName, { [alias]: 'abc123' }, [
                        { tileId: 20, insightId: 99, insightShortId: 'other' },
                    ])
                    await jest.advanceTimersByTimeAsync(200)
                    await jest.advanceTimersByTimeAsync(0)

                    expect(dashboardRequests(getResponse, 5)).toHaveLength(1)
                    expect(dashboardRequests(getResponse, 6)).toHaveLength(0)
                } finally {
                    getResponse.mockRestore()
                    unrelatedSyncLogic.unmount()
                    unrelatedDashboardLogic.unmount()
                }
            }
        )
    })

    it('uses numeric primary-key semantics and fails closed for contradictions or ambiguous short IDs', async () => {
        const numericShortIdTiles = [{ tileId: 10, insightId: 42, insightShortId: '999' }]
        const getResponse = mockDashboardResponses(5, Promise.resolve(dashboardResponse(5, [])))

        logic.actions.agentToolCompleted('insight-update', { shortId: '42' }, numericShortIdTiles)
        await jest.advanceTimersByTimeAsync(200)
        await jest.advanceTimersByTimeAsync(0)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(1)

        logic.actions.agentToolCompleted('insight-update', { id: 42, short_id: 'other' }, baselineTiles)
        logic.actions.agentToolCompleted('insight-delete', { shortId: '999' }, numericShortIdTiles)
        await jest.advanceTimersByTimeAsync(200)

        expect(dashboardRequests(getResponse, 5)).toHaveLength(1)
        getResponse.mockRestore()
    })

    test.each([
        ['new tile', { baselineTileIds: [10], candidateTileIds: [], candidateInsightIds: [] }, [10, 12], [12]],
        ['updated tile', { baselineTileIds: [10], candidateTileIds: [10], candidateInsightIds: [] }, [10], [10]],
        ['deleted tile', { baselineTileIds: [10], candidateTileIds: [10], candidateInsightIds: [] }, [], []],
        [
            'updated insight',
            { baselineTileIds: [10], candidateTileIds: [], candidateInsightIds: ['abc123'] },
            [{ tileId: 10, insightId: 42, insightShortId: 'abc123' }],
            [10],
        ],
    ])('resolves %s after reload', (_name, pending, refreshed, expected) => {
        const refreshedTiles =
            typeof refreshed[0] === 'number'
                ? (refreshed as number[]).map((tileId) => ({ tileId }))
                : (refreshed as DashboardTileIdentity[])
        expect(resolveHighlightedTileIds(pending as DashboardAiPendingChange, refreshedTiles)).toEqual(expected)
    })

    it('reloads a matching dashboard mutation and highlights its refreshed tile', async () => {
        await expectLogic(logic, () => {
            logic.actions.agentToolCompleted('dashboard-delete-tile', { id: 5, tile_id: 10 }, baselineTiles)
        })
            .toDispatchActions(['agentToolCompleted', 'queueDashboardReload', 'startDashboardReload', 'loadDashboard'])
            .toMatchValues({
                activeReload: {
                    generation: 1,
                    change: {
                        baselineTileIds: [10, 11],
                        candidateTileIds: [10],
                        candidateInsightIds: [],
                    },
                },
                queuedChange: null,
            })

        const generation = logic.values.activeReload!.generation
        const loadPayload = {
            action: DashboardLoadAction.Update,
            dashboardAiSyncGeneration: generation,
        }
        expect(generation).toBe(1)
        await expectLogic(logic, () => {
            dashboardLogic({ id: 5 }).actions.loadDashboardSuccess(
                { tiles: baselineTiles.map((tile) => ({ id: tile.tileId })) } as any,
                loadPayload
            )
        })
            .toDispatchActions(['loadDashboardSuccess', 'completeDashboardReload', 'setAiHighlightedTileIds'])
            .toMatchValues({ aiHighlightedTileIds: [10], activeReload: null, queuedChange: null })
    })

    it('serializes AI reloads and binds each completion to its own mutation snapshot', async () => {
        const firstReload = deferred<Response>()
        const secondReload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, firstReload.promise, secondReload.promise)

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 10 }] }, baselineTiles)
        await jest.advanceTimersByTimeAsync(200)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(1)

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 11 }] }, baselineTiles)
        await jest.advanceTimersByTimeAsync(200)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(1)

        firstReload.resolve(dashboardResponse(5, [dashboardTile(10), dashboardTile(11)]))
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.aiHighlightedTileIds).toEqual([10])

        await jest.advanceTimersByTimeAsync(200)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(2)

        secondReload.resolve(dashboardResponse(5, [dashboardTile(10), dashboardTile(11), dashboardTile(12)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([10, 11, 12])
        expect(logic.values.aiHighlightedTileIds).toEqual([11, 12])
        getResponse.mockRestore()
    })

    it('clears a failed AI generation before an unrelated manual reload succeeds', async () => {
        const aiReload = deferred<Response>()
        const manualReload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, aiReload.promise, manualReload.promise)

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 10 }] }, baselineTiles)
        await jest.advanceTimersByTimeAsync(200)
        aiReload.reject(new Error('AI dashboard reload failed'))
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.activeReload).toBeNull()
        expect(logic.values.queuedChange).toBeNull()

        dashboardSceneLogic.actions.loadDashboard({ action: DashboardLoadAction.Update })
        await jest.advanceTimersByTimeAsync(200)
        manualReload.resolve(dashboardResponse(5, [dashboardTile(99)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([99])
        expect(logic.values.aiHighlightedTileIds).toEqual([])
        expect(logic.values.activeReload).toBeNull()
        getResponse.mockRestore()
    })

    it('highlights an existing tile patched through dashboard-update tiles', async () => {
        const reload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, reload.promise)

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 10 }] }, baselineTiles)
        await jest.advanceTimersByTimeAsync(200)
        reload.resolve(dashboardResponse(5, [dashboardTile(10), dashboardTile(11)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.aiHighlightedTileIds).toEqual([10])
        getResponse.mockRestore()
    })

    it('keeps the active snapshot isolated and merges later queued candidates against their first baseline', () => {
        const laterSnapshot: DashboardTileIdentity[] = [{ tileId: 99, insightId: 42, insightShortId: 'abc123' }]

        logic.actions.agentToolCompleted('dashboard-delete-tile', { id: 5, tile_id: 10 }, baselineTiles)
        logic.actions.agentToolCompleted('insight-update', { id: 42 }, laterSnapshot)
        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 100 }] }, [{ tileId: 100 }])

        expect(logic.values.activeReload?.change).toEqual({
            baselineTileIds: [10, 11],
            candidateTileIds: [10],
            candidateInsightIds: [],
        })
        expect(logic.values.queuedChange).toEqual({
            baselineTileIds: [99],
            candidateTileIds: [100],
            candidateInsightIds: [42],
        })
    })

    it('clears highlights after five seconds', async () => {
        logic.actions.setAiHighlightedTileIds([10])
        expect(logic.values.aiHighlightedTileIds).toEqual([10])

        await jest.advanceTimersByTimeAsync(DASHBOARD_AI_HIGHLIGHT_MS)

        expect(logic.values.aiHighlightedTileIds).toEqual([])
    })

    it('does not reload the open dashboard for an unrelated tool call', () => {
        expectLogic().clearHistory()

        expectLogic(logic, () => {
            logic.actions.agentToolCompleted('dashboard-update', { id: 8 }, baselineTiles)
        }).toNotHaveDispatchedActions(['loadDashboard'])

        expect(logic.values.activeReload).toBeNull()
        expect(logic.values.queuedChange).toBeNull()
    })

    it('does nothing when subscription and alert views are not mounted', () => {
        expectLogic().clearHistory()

        expectLogic(logic, () => {
            logic.actions.agentToolCompleted('subscriptions-create', { dashboard: 5 }, baselineTiles)
            logic.actions.agentToolCompleted('alert-create', { insight: 42 }, baselineTiles)
        }).toNotHaveDispatchedActions(['loadDashboard'])

        expect(logic.values.activeReload).toBeNull()
        expect(logic.values.queuedChange).toBeNull()
        expect(subscriptionsLogic.isMounted({ dashboardId: 5 })).toBe(false)
        expect(insightAlertsLogic.findAllMounted()).toHaveLength(0)
        expect(subscriptionsListSpy).not.toHaveBeenCalled()
        expect(alertsListSpy).not.toHaveBeenCalled()
    })
})

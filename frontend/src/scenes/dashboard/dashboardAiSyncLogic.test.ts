import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
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

const dashboardResponseWithQueuedCommitRace = (
    dashboardId: number,
    tiles: DashboardTile<QueryBasedInsightModel>[],
    onCommitWindow: () => void
): Response => {
    const response = dashboardResponse(dashboardId, tiles)
    const getHeader = response.headers.get.bind(response.headers)
    let actionQueued = false
    jest.spyOn(response.headers, 'get').mockImplementation((name) => {
        if (!actionQueued && name.toLowerCase() === 'content-length') {
            actionQueued = true
            queueMicrotask(onCommitWindow)
        }
        return getHeader(name)
    })
    return response
}

const dashboardErrorWithQueuedCommitRace = (
    status: number,
    code: string | null,
    onCommitWindow: () => void
): ApiError => {
    const error = new ApiError(`Dashboard request failed with status ${status}`, status, undefined, { code })
    let actionQueued = false
    Object.defineProperty(error, 'status', {
        configurable: true,
        get: () => {
            if (!actionQueued) {
                actionQueued = true
                queueMicrotask(onCommitWindow)
            }
            return status
        },
    })
    return error
}

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
                    requestToken: expect.anything(),
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
            dashboardAiSync: {
                generation,
                requestToken: logic.values.activeReload!.requestToken,
            },
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

    it('keeps a newer manual response and promotes one queued AI snapshot after the older AI reload settles', async () => {
        const aiReload = deferred<Response>()
        const manualReload = deferred<Response>()
        const queuedAiReload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, aiReload.promise, manualReload.promise, queuedAiReload.promise)

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 10 }] }, baselineTiles)
        await jest.advanceTimersByTimeAsync(200)

        dashboardSceneLogic.actions.loadDashboard({ action: DashboardLoadAction.Update })
        await jest.advanceTimersByTimeAsync(200)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(2)

        manualReload.resolve(dashboardResponse(5, [dashboardTile(99)]))
        await jest.advanceTimersByTimeAsync(0)
        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([99])

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 11 }] }, [{ tileId: 99 }])
        expect(logic.values.activeReload?.generation).toBe(1)
        expect(logic.values.queuedChange).toEqual({
            baselineTileIds: [99],
            candidateTileIds: [11],
            candidateInsightIds: [],
        })

        aiReload.resolve(dashboardResponse(5, [dashboardTile(10)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([99])
        expect(logic.values.aiHighlightedTileIds).toEqual([])
        expect(logic.values.activeReload?.generation).toBe(2)
        expect(logic.values.queuedChange).toBeNull()

        await jest.advanceTimersByTimeAsync(200)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(3)

        queuedAiReload.resolve(dashboardResponse(5, [dashboardTile(99), dashboardTile(11)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([99, 11])
        expect(logic.values.aiHighlightedTileIds).toEqual([11])
        expect(logic.values.activeReload).toBeNull()
        getResponse.mockRestore()
    })

    it('keeps a newer dashboard load pending when an older success reaches the generated dispatch window', async () => {
        const oldReload = deferred<Response>()
        const newReload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, oldReload.promise, newReload.promise)

        dashboardSceneLogic.actions.loadDashboard({ action: DashboardLoadAction.Update })
        await jest.advanceTimersByTimeAsync(200)

        oldReload.resolve(
            dashboardResponseWithQueuedCommitRace(5, [dashboardTile(10)], () => {
                dashboardSceneLogic.actions.loadDashboard({ action: DashboardLoadAction.Update })
            })
        )
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([])
        expect(dashboardSceneLogic.values.dashboardLoading).toBe(true)

        await jest.advanceTimersByTimeAsync(200)
        newReload.resolve(dashboardResponse(5, [dashboardTile(99)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([99])
        expect(dashboardSceneLogic.values.dashboardLoading).toBe(false)
        getResponse.mockRestore()
    })

    test.each([
        ['404', 404, null],
        ['403 access denied', 403, 'permission_denied'],
    ])('ignores a stale %s in the generated failure dispatch window', async (_label, status, code) => {
        const oldReload = deferred<Response>()
        const newReload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, oldReload.promise, newReload.promise)

        dashboardSceneLogic.actions.loadDashboard({ action: DashboardLoadAction.Update })
        await jest.advanceTimersByTimeAsync(200)

        oldReload.reject(
            dashboardErrorWithQueuedCommitRace(status, code, () => {
                dashboardSceneLogic.actions.loadDashboard({ action: DashboardLoadAction.Update })
            })
        )
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([])
        expect(dashboardSceneLogic.values.dashboardLoading).toBe(true)
        expect(dashboardSceneLogic.values.error404).toBe(false)
        expect(dashboardSceneLogic.values.accessDeniedToDashboard).toBe(false)
        expect(dashboardSceneLogic.values.dashboardFailedToLoad).toBe(false)

        await jest.advanceTimersByTimeAsync(200)
        newReload.resolve(dashboardResponse(5, [dashboardTile(99)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([99])
        expect(dashboardSceneLogic.values.dashboardLoading).toBe(false)
        getResponse.mockRestore()
    })

    it('does not let an obsolete mounted lifetime consume success for a new reload with the same generation', async () => {
        const oldReload = deferred<Response>()
        const newReload = deferred<Response>()
        const getResponse = mockDashboardResponses(5, oldReload.promise, newReload.promise)

        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 10 }] }, baselineTiles)
        await jest.advanceTimersByTimeAsync(200)
        expect(logic.values.activeReload?.generation).toBe(1)

        oldReload.resolve(
            dashboardResponseWithQueuedCommitRace(5, [dashboardTile(10)], () => {
                logic.unmount()
                logic = dashboardAiSyncLogic({ dashboardId: 5 })
                logic.mount()
                logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 20 }] }, baselineTiles)
            })
        )
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.activeReload?.generation).toBe(1)
        expect(logic.values.aiHighlightedTileIds).toEqual([])
        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([])

        await jest.advanceTimersByTimeAsync(200)
        expect(dashboardRequests(getResponse, 5)).toHaveLength(2)

        newReload.resolve(dashboardResponse(5, [dashboardTile(10), dashboardTile(20)]))
        await jest.advanceTimersByTimeAsync(0)

        expect(dashboardSceneLogic.values.dashboard?.tiles.map((tile) => tile.id)).toEqual([10, 20])
        expect(logic.values.aiHighlightedTileIds).toEqual([20])
        expect(logic.values.activeReload).toBeNull()
        getResponse.mockRestore()
    })

    it('requires the AI request token when generations match across mounted lifetimes', () => {
        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 10 }] }, baselineTiles)
        const obsoleteRequest = logic.values.activeReload!

        logic.unmount()
        logic = dashboardAiSyncLogic({ dashboardId: 5 })
        logic.mount()
        logic.actions.agentToolCompleted('dashboard-update', { id: 5, tiles: [{ id: 20 }] }, baselineTiles)
        const currentRequest = logic.values.activeReload!

        expect(obsoleteRequest.generation).toBe(currentRequest.generation)
        expect(obsoleteRequest.requestToken).not.toBe(currentRequest.requestToken)

        dashboardSceneLogic.actions.loadDashboardSuccess({ tiles: [dashboardTile(10)] } as any, {
            action: DashboardLoadAction.Update,
            dashboardAiSync: {
                generation: obsoleteRequest.generation,
                requestToken: obsoleteRequest.requestToken,
            },
        })

        expect(logic.values.activeReload).toBe(currentRequest)
        expect(logic.values.aiHighlightedTileIds).toEqual([])
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

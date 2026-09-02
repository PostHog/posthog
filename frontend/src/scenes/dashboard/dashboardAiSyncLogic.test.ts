import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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

describe('dashboardAiSyncLogic', () => {
    let logic: ReturnType<typeof dashboardAiSyncLogic.build>
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
        logic = dashboardAiSyncLogic({ dashboardId: 5 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        subscriptionsListSpy.mockRestore()
        alertsListSpy.mockRestore()
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
            .toDispatchActions(['agentToolCompleted', 'queueDashboardReload', 'loadDashboard'])
            .toMatchValues({
                pendingChange: {
                    baselineTileIds: [10, 11],
                    candidateTileIds: [10],
                    candidateInsightIds: [],
                },
            })

        await expectLogic(logic, () => {
            dashboardLogic({ id: 5 }).actions.loadDashboardSuccess(
                { tiles: baselineTiles.map((tile) => ({ id: tile.tileId })) } as any,
                {
                    action: DashboardLoadAction.Update,
                }
            )
        })
            .toDispatchActions(['loadDashboardSuccess', 'completeDashboardReload', 'setAiHighlightedTileIds'])
            .toMatchValues({ aiHighlightedTileIds: [10], pendingChange: null })
    })

    it('merges queued candidates while retaining the first baseline', () => {
        const laterSnapshot: DashboardTileIdentity[] = [{ tileId: 99, insightId: 42, insightShortId: 'abc123' }]

        logic.actions.agentToolCompleted('dashboard-delete-tile', { id: 5, tile_id: 10 }, baselineTiles)
        logic.actions.agentToolCompleted('insight-update', { id: 42 }, laterSnapshot)

        expect(logic.values.pendingChange).toEqual({
            baselineTileIds: [10, 11],
            candidateTileIds: [10],
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

        expect(logic.values.pendingChange).toBeNull()
    })

    it('does nothing when subscription and alert views are not mounted', () => {
        expectLogic().clearHistory()

        expectLogic(logic, () => {
            logic.actions.agentToolCompleted('subscriptions-create', { dashboard: 5 }, baselineTiles)
            logic.actions.agentToolCompleted('alert-create', { insight: 42 }, baselineTiles)
        }).toNotHaveDispatchedActions(['loadDashboard'])

        expect(logic.values.pendingChange).toBeNull()
        expect(subscriptionsLogic.isMounted({ dashboardId: 5 })).toBe(false)
        expect(insightAlertsLogic.findAllMounted()).toHaveLength(0)
        expect(subscriptionsListSpy).not.toHaveBeenCalled()
        expect(alertsListSpy).not.toHaveBeenCalled()
    })
})

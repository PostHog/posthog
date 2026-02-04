import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import type { QueryBasedInsightModel } from '~/types'

import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import type { insightDashboardModalLogicType } from './insightDashboardModalLogicType'

export type OptimisticDashboardState = Record<number, boolean>

export const insightDashboardModalLogic = kea<insightDashboardModalLogicType>([
    path(['scenes', 'saved-insights', 'insightDashboardModalLogic']),
    connect({
        actions: [
            addSavedInsightsModalLogic,
            ['addInsightToDashboard', 'removeInsightFromDashboard', 'dashboardUpdateFailed'],
        ],
        values: [addSavedInsightsModalLogic, ['dashboardUpdatesInProgress']],
    }),
    actions({
        setOptimisticDashboardState: (insightId: number, inDashboard: boolean) => ({ insightId, inDashboard }),
        clearOptimisticDashboardState: (insightId: number) => ({ insightId }),
        syncOptimisticStateWithDashboard: (tiles: { insight?: { id: number } | null }[]) => ({ tiles }),
        toggleInsightOnDashboard: (
            insight: QueryBasedInsightModel,
            dashboardId: number,
            currentlyInDashboard: boolean
        ) => ({
            insight,
            dashboardId,
            currentlyInDashboard,
        }),
    }),
    reducers({
        optimisticDashboardState: [
            {} as OptimisticDashboardState,
            {
                setOptimisticDashboardState: (state, { insightId, inDashboard }) => ({
                    ...state,
                    [insightId]: inDashboard,
                }),
                clearOptimisticDashboardState: (state, { insightId }) => {
                    const { [insightId]: _, ...rest } = state
                    return rest
                },
                dashboardUpdateFailed: (state, { insightId }) => {
                    const { [insightId]: _, ...rest } = state
                    return rest
                },
                syncOptimisticStateWithDashboard: (state, { tiles }) => {
                    const next = { ...state }
                    let changed = false
                    for (const idStr of Object.keys(next)) {
                        const id = Number(idStr)
                        const actuallyInDashboard = tiles.some((tile) => tile.insight?.id === id)
                        if (next[id] === actuallyInDashboard) {
                            delete next[id]
                            changed = true
                        }
                    }
                    return changed ? next : state
                },
            },
        ],
    }),
    selectors({
        isInsightInDashboard: [
            (s) => [s.optimisticDashboardState],
            (
                optimisticState: OptimisticDashboardState
            ): ((
                insight: QueryBasedInsightModel,
                dashboardTiles?: { insight?: { id: number } | null }[]
            ) => boolean) => {
                return (
                    insight: QueryBasedInsightModel,
                    dashboardTiles?: { insight?: { id: number } | null }[]
                ): boolean => {
                    if (insight.id in optimisticState) {
                        return optimisticState[insight.id]
                    }
                    return dashboardTiles?.some((tile) => tile.insight?.id === insight.id) ?? false
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        toggleInsightOnDashboard: ({ insight, dashboardId, currentlyInDashboard }) => {
            if (values.dashboardUpdatesInProgress[insight.id]) {
                return
            }
            actions.setOptimisticDashboardState(insight.id, !currentlyInDashboard)
            if (currentlyInDashboard) {
                actions.removeInsightFromDashboard(insight, dashboardId)
            } else {
                actions.addInsightToDashboard(insight, dashboardId)
            }
        },
    })),
])

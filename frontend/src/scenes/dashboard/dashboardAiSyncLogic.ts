import { LogicWrapper, MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { extractInsightToolReferences, insightToolTargetsCurrentInsight } from 'scenes/insights/insightToolTargeting'
import { urls } from 'scenes/urls'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'

import type { Node } from '../../queries/schema/schema-general'
import type { DashboardType } from '../../types'

export const DASHBOARD_AI_HIGHLIGHT_MS = 5_000

export const DASHBOARD_AI_TOOL_NAMES = [
    'dashboard-update',
    'dashboard-create-text-tile',
    'dashboard-update-text-tile',
    'dashboard-delete-tile',
    'dashboard-reorder-tiles',
    'dashboard-tile-copy',
    'dashboard-widgets-batch-add',
    'dashboard-widgets-batch-update',
    'dashboards-move-tile-partial-update',
    'dashboard-delete',
    'insight-create',
    'insight-update',
    'insight-delete',
    'subscriptions-create',
    'subscriptions-partial-update',
    'subscriptions-delete',
    'alert-create',
    'alert-update',
    'alert-delete',
] as const

export interface DashboardTileIdentity {
    tileId: number
    insightId?: number
    insightShortId?: string
}

export interface DashboardAiPendingChange {
    baselineTileIds: number[]
    candidateTileIds: number[]
    candidateInsightIds: Array<number | string>
}

interface DashboardAiReloadCycle {
    generation: number
    change: DashboardAiPendingChange
}

interface DashboardAiLoadPayload {
    action: DashboardLoadAction
    dashboardAiSyncGeneration: number
}

const asId = (value: unknown): number | string | null => {
    if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
        return value
    }
    if (typeof value === 'string' && value.length > 0) {
        return /^\d+$/.test(value) ? Number(value) : value
    }
    return null
}

const sameId = (left: unknown, right: unknown): boolean => {
    const leftId = asId(left)
    const rightId = asId(right)
    return leftId !== null && rightId !== null && String(leftId) === String(rightId)
}

const numericId = (value: unknown): number | null => {
    const id = asId(value)
    return typeof id === 'number' ? id : null
}

const idsFrom = (value: unknown): number[] => {
    if (Array.isArray(value)) {
        return value.flatMap(idsFrom)
    }
    if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>
        return [record.id, record.tile_id, record.tileId].flatMap(idsFrom)
    }
    const id = numericId(value)
    return id === null ? [] : [id]
}

export function snapshotDashboardTiles(tiles: DashboardTile<QueryBasedInsightModel>[]): DashboardTileIdentity[] {
    return tiles.map((tile) => ({
        tileId: tile.id,
        insightId: tile.insight?.id,
        insightShortId: tile.insight?.short_id,
    }))
}

const structuralDashboardTools = new Set<string>([
    'dashboard-update',
    'dashboard-create-text-tile',
    'dashboard-update-text-tile',
    'dashboard-delete-tile',
    'dashboard-reorder-tiles',
    'dashboard-tile-copy',
    'dashboard-widgets-batch-add',
    'dashboard-widgets-batch-update',
    'dashboard-delete',
])

export function dashboardToolTargetsCurrentDashboard(
    toolName: string,
    innerInput: Record<string, unknown>,
    dashboardId: number,
    tileSnapshot: DashboardTileIdentity[]
): boolean {
    if (structuralDashboardTools.has(toolName)) {
        return sameId(innerInput.id, dashboardId)
    }

    if (toolName === 'dashboards-move-tile-partial-update') {
        return sameId(innerInput.id, dashboardId) || sameId(innerInput.to_dashboard, dashboardId)
    }

    if (toolName === 'insight-create') {
        return Array.isArray(innerInput.dashboards) && innerInput.dashboards.some((id) => sameId(id, dashboardId))
    }

    if (toolName === 'insight-update') {
        return (
            (Array.isArray(innerInput.dashboards) && innerInput.dashboards.some((id) => sameId(id, dashboardId))) ||
            tileSnapshot.some((tile) =>
                insightToolTargetsCurrentInsight(innerInput, {
                    id: tile.insightId,
                    short_id: tile.insightShortId,
                })
            )
        )
    }

    if (toolName === 'insight-delete') {
        return tileSnapshot.some((tile) =>
            insightToolTargetsCurrentInsight(innerInput, {
                id: tile.insightId,
                short_id: tile.insightShortId,
            })
        )
    }

    return false
}

const extractCandidateTileIds = (toolName: string, innerInput: Record<string, unknown>): number[] => {
    if (toolName === 'dashboard-delete') {
        return []
    }

    return [
        ...idsFrom(innerInput.tile_id),
        ...idsFrom(innerInput.tileId),
        ...idsFrom(innerInput.tile),
        ...idsFrom(innerInput.tiles),
        ...idsFrom(innerInput.widgets),
        ...idsFrom(innerInput.tile_order),
    ]
}

const extractCandidateInsightIds = (toolName: string, innerInput: Record<string, unknown>): Array<number | string> => {
    if (toolName !== 'insight-update' && toolName !== 'insight-delete') {
        return []
    }
    return extractInsightToolReferences(innerInput)
}

const uniqueIds = <T extends number | string>(ids: T[]): T[] =>
    ids.filter((id, index) => ids.findIndex((candidate) => sameId(candidate, id)) === index)

export function mergePendingChange(
    pendingChange: DashboardAiPendingChange | null,
    change: DashboardAiPendingChange
): DashboardAiPendingChange {
    if (!pendingChange) {
        return {
            baselineTileIds: uniqueIds(change.baselineTileIds),
            candidateTileIds: uniqueIds(change.candidateTileIds),
            candidateInsightIds: uniqueIds(change.candidateInsightIds),
        }
    }

    return {
        baselineTileIds: pendingChange.baselineTileIds,
        candidateTileIds: uniqueIds([...pendingChange.candidateTileIds, ...change.candidateTileIds]),
        candidateInsightIds: uniqueIds([...pendingChange.candidateInsightIds, ...change.candidateInsightIds]),
    }
}

export function resolveHighlightedTileIds(
    pending: DashboardAiPendingChange,
    refreshedTiles: DashboardTileIdentity[]
): number[] {
    const baseline = new Set(pending.baselineTileIds)
    const explicitTiles = new Set(pending.candidateTileIds)
    const explicitInsights = new Set(pending.candidateInsightIds.map(String))

    return refreshedTiles
        .filter(
            (tile) =>
                !baseline.has(tile.tileId) ||
                explicitTiles.has(tile.tileId) ||
                (tile.insightId !== undefined && explicitInsights.has(String(tile.insightId))) ||
                (tile.insightShortId !== undefined && explicitInsights.has(tile.insightShortId))
        )
        .map((tile) => tile.tileId)
}

export interface DashboardAiSyncLogicProps {
    dashboardId: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardAiSyncLogicValues {
    dashboard: DashboardType<QueryBasedInsightModel> | null // dashboardLogic
    tiles: DashboardTile<QueryBasedInsightModel<Node<Record<string, any>>>>[] // dashboardLogic
    activeReload: DashboardAiReloadCycle | null
    aiHighlightedTileIds: number[]
    queuedChange: DashboardAiPendingChange | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardAiSyncLogicActions {
    loadDashboard: (payload: { action: DashboardLoadAction }) => {
        action: DashboardLoadAction
    } // dashboardLogic
    loadDashboardSuccess: (
        dashboard: DashboardType<QueryBasedInsightModel<Node<Record<string, any>>>> | null,
        payload?:
            | {
                  action: DashboardLoadAction
              }
            | undefined
    ) => {
        dashboard: DashboardType<QueryBasedInsightModel<Node<Record<string, any>>>> | null
        payload?: {
            action: DashboardLoadAction
        }
    } // dashboardLogic
    agentToolCompleted: (
        toolName: string,
        innerInput: Record<string, unknown> | null,
        baselineTiles: DashboardTileIdentity[]
    ) => {
        baselineTiles: DashboardTileIdentity[]
        innerInput: Record<string, unknown> | null
        toolName: string
    }
    clearAiHighlightedTileIds: () => {
        value: true
    }
    completeDashboardReload: (
        generation: number,
        tileIds: number[]
    ) => {
        generation: number
        tileIds: number[]
    }
    failDashboardReload: (generation: number) => {
        generation: number
    }
    queueDashboardReload: (change: DashboardAiPendingChange) => {
        change: DashboardAiPendingChange
    }
    setAiHighlightedTileIds: (tileIds: number[]) => {
        tileIds: number[]
    }
    startDashboardReload: (
        generation: number,
        change: DashboardAiPendingChange
    ) => {
        change: DashboardAiPendingChange
        generation: number
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardAiSyncLogicMeta {
    key: number
}

export type dashboardAiSyncLogicType = MakeLogicType<
    dashboardAiSyncLogicValues,
    dashboardAiSyncLogicActions,
    DashboardAiSyncLogicProps,
    dashboardAiSyncLogicMeta
>

export const dashboardAiSyncLogic: LogicWrapper<dashboardAiSyncLogicType> = kea<dashboardAiSyncLogicType>([
    props({} as DashboardAiSyncLogicProps),
    key(({ dashboardId }) => dashboardId),
    path((key) => ['scenes', 'dashboard', 'dashboardAiSyncLogic', key]),
    connect((logicProps: DashboardAiSyncLogicProps) => ({
        actions: [dashboardLogic({ id: logicProps.dashboardId }), ['loadDashboard', 'loadDashboardSuccess']],
        values: [dashboardLogic({ id: logicProps.dashboardId }), ['dashboard', 'tiles']],
    })),
    actions({
        agentToolCompleted: (
            toolName: string,
            innerInput: Record<string, unknown> | null,
            baselineTiles: DashboardTileIdentity[]
        ) => ({ toolName, innerInput, baselineTiles }),
        queueDashboardReload: (change: DashboardAiPendingChange) => ({ change }),
        startDashboardReload: (generation: number, change: DashboardAiPendingChange) => ({ generation, change }),
        completeDashboardReload: (generation: number, tileIds: number[]) => ({ generation, tileIds }),
        failDashboardReload: (generation: number) => ({ generation }),
        setAiHighlightedTileIds: (tileIds: number[]) => ({ tileIds }),
        clearAiHighlightedTileIds: true,
    }),
    reducers({
        activeReload: [
            null as DashboardAiReloadCycle | null,
            {
                startDashboardReload: (_, { generation, change }) => ({ generation, change }),
                completeDashboardReload: (state, { generation }) => (state?.generation === generation ? null : state),
                failDashboardReload: (state, { generation }) => (state?.generation === generation ? null : state),
            },
        ],
        queuedChange: [
            null as DashboardAiPendingChange | null,
            {
                queueDashboardReload: (state, { change }) => mergePendingChange(state, change),
                startDashboardReload: () => null,
            },
        ],
        aiHighlightedTileIds: [
            [] as number[],
            {
                setAiHighlightedTileIds: (_, { tileIds }) => tileIds,
                clearAiHighlightedTileIds: () => [],
            },
        ],
    }),
    listeners(({ actions, cache, props, values }) => {
        const startQueuedReload = (): void => {
            if (values.activeReload || !values.queuedChange) {
                return
            }
            cache.nextDashboardAiReloadGeneration = (cache.nextDashboardAiReloadGeneration ?? 0) + 1
            actions.startDashboardReload(cache.nextDashboardAiReloadGeneration, values.queuedChange)
        }

        return {
            queueDashboardReload: startQueuedReload,
            startDashboardReload: async ({ generation }) => {
                const loadPayload: DashboardAiLoadPayload = {
                    action: DashboardLoadAction.Update,
                    dashboardAiSyncGeneration: generation,
                }
                try {
                    await dashboardLogic({ id: props.dashboardId }).asyncActions.loadDashboard(loadPayload)
                } finally {
                    // kea-loaders does not retain the original request payload on failure. The request-specific
                    // async action settles after success/failure, so an uncleared generation failed or cancelled.
                    if (values.activeReload?.generation === generation) {
                        actions.failDashboardReload(generation)
                    }
                }
            },
            loadDashboardSuccess: ({ dashboard, payload }) => {
                const generation = (payload as Partial<DashboardAiLoadPayload> | undefined)?.dashboardAiSyncGeneration
                const activeReload = values.activeReload
                if (!dashboard || generation === undefined || activeReload?.generation !== generation) {
                    return
                }
                actions.completeDashboardReload(
                    generation,
                    resolveHighlightedTileIds(activeReload.change, snapshotDashboardTiles(dashboard.tiles ?? []))
                )
            },
            completeDashboardReload: ({ tileIds }) => {
                actions.setAiHighlightedTileIds(tileIds)
                startQueuedReload()
            },
            failDashboardReload: startQueuedReload,
            setAiHighlightedTileIds: ({ tileIds }) => {
                cache.disposables.dispose('aiTileHighlight')
                if (tileIds.length === 0) {
                    return
                }
                cache.disposables.add(() => {
                    const timeout = window.setTimeout(
                        () => actions.clearAiHighlightedTileIds(),
                        DASHBOARD_AI_HIGHLIGHT_MS
                    )
                    return () => window.clearTimeout(timeout)
                }, 'aiTileHighlight')
            },
            clearAiHighlightedTileIds: () => {
                cache.disposables.dispose('aiTileHighlight')
            },
            agentToolCompleted: ({ toolName, innerInput, baselineTiles }) => {
                if (!innerInput) {
                    return
                }

                if (toolName === 'dashboard-delete' && sameId(innerInput.id, props.dashboardId)) {
                    router.actions.push(urls.dashboards())
                    return
                }

                if (dashboardToolTargetsCurrentDashboard(toolName, innerInput, props.dashboardId, baselineTiles)) {
                    actions.queueDashboardReload({
                        baselineTileIds: baselineTiles.map((tile) => tile.tileId),
                        candidateTileIds: extractCandidateTileIds(toolName, innerInput),
                        candidateInsightIds: extractCandidateInsightIds(toolName, innerInput),
                    })
                    return
                }

                const mountedSubscriptionsLogic = subscriptionsLogic.findMounted({ dashboardId: props.dashboardId })
                if (toolName === 'subscriptions-create' && sameId(innerInput.dashboard, props.dashboardId)) {
                    mountedSubscriptionsLogic?.actions.loadAllSubscriptions()
                    return
                }
                if (
                    (toolName === 'subscriptions-partial-update' || toolName === 'subscriptions-delete') &&
                    mountedSubscriptionsLogic &&
                    [
                        ...mountedSubscriptionsLogic.values.subscriptions,
                        ...mountedSubscriptionsLogic.values.insightSubscriptions,
                    ].some((subscription) => sameId(subscription.id, innerInput.id))
                ) {
                    mountedSubscriptionsLogic.actions.loadAllSubscriptions()
                    return
                }

                const mountedAlertLogics = insightAlertsLogic
                    .findAllMounted()
                    .filter((alertLogic) =>
                        baselineTiles.some((tile) => sameId(tile.insightId, alertLogic.props.insightId))
                    )
                if (toolName === 'alert-create') {
                    mountedAlertLogics
                        .filter((alertLogic) => sameId(alertLogic.props.insightId, innerInput.insight))
                        .forEach((alertLogic) => alertLogic.actions.loadAlerts())
                    return
                }
                if (toolName === 'alert-update' || toolName === 'alert-delete') {
                    mountedAlertLogics
                        .filter((alertLogic) =>
                            alertLogic.values.alerts.some((alert) => sameId(alert.id, innerInput.id))
                        )
                        .forEach((alertLogic) => alertLogic.actions.loadAlerts())
                }
            },
        }
    }),
])

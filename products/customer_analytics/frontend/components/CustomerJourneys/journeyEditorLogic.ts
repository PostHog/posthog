import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { extractLayerIndex, PathExpansion } from 'scenes/funnels/FunnelFlowGraph/pathFlowUtils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { EventsNode, FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { insightsApi } from '~/scenes/insights/utils/api'
import { ActionFilter, FunnelPathType, PropertyFilterType, PropertyOperator } from '~/types'

import { customerJourneysLogic } from './customerJourneysLogic'
import type { journeyEditorLogicType } from './journeyEditorLogicType'

export interface StagedNode {
    nodeId: string
    eventName: string
}

export interface ExpansionContext {
    expansion: PathExpansion
    funnelStepCount: number
}

function eventNameToActionFilter(eventName: string, order: number): ActionFilter {
    const isPageview = /^https?:\/\//.test(eventName)
    return {
        id: isPageview ? '$pageview' : eventName,
        name: isPageview ? '$pageview' : eventName,
        type: 'events',
        order,
        ...(isPageview && {
            properties: [
                {
                    key: '$current_url',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                    value: eventName,
                },
            ],
        }),
    }
}

function layerIndexFromNodeId(nodeId: string): number {
    const rawName = nodeId.replace(/^path-/, '')
    return extractLayerIndex(rawName)
}

export const journeyEditorLogic = kea<journeyEditorLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerJourneys', 'journeyEditorLogic']),

    actions({
        stagePathNode: (nodeId: string, eventName: string, expansion: PathExpansion, funnelStepCount: number) => ({
            nodeId,
            eventName,
            expansion,
            funnelStepCount,
        }),
        unstagePathNode: (nodeId: string) => ({ nodeId }),
        toggleStagedNodeOptional: (nodeId: string) => ({ nodeId }),
        saveChanges: true,
        cancelChanges: true,
        saveChangesSuccess: true,
        saveChangesFailure: (error: string) => ({ error }),
    }),

    reducers({
        stagedNodes: [
            [] as StagedNode[],
            {
                stagePathNode: (state, { nodeId, eventName }) => [...state, { nodeId, eventName }],
                unstagePathNode: (state, { nodeId }) => state.filter((n) => n.nodeId !== nodeId),
                cancelChanges: () => [],
                saveChangesSuccess: () => [],
            },
        ],
        stagedNodeOptional: [
            {} as Record<string, boolean>,
            {
                toggleStagedNodeOptional: (state, { nodeId }) => ({
                    ...state,
                    [nodeId]: !state[nodeId],
                }),
                unstagePathNode: (state, { nodeId }) => {
                    const { [nodeId]: _, ...rest } = state
                    return rest
                },
                cancelChanges: () => ({}),
                saveChangesSuccess: () => ({}),
            },
        ],
        expansionContext: [
            null as ExpansionContext | null,
            {
                stagePathNode: (_, { expansion, funnelStepCount }) => ({ expansion, funnelStepCount }),
                cancelChanges: () => null,
                saveChangesSuccess: () => null,
            },
        ],
        isSaving: [
            false,
            {
                saveChanges: () => true,
                saveChangesSuccess: () => false,
                saveChangesFailure: () => false,
            },
        ],
    }),

    selectors({
        isEditMode: [(s) => [s.stagedNodes], (stagedNodes): boolean => stagedNodes.length > 0],
        stagedNodeIds: [
            (s) => [s.stagedNodes],
            (stagedNodes): Set<string> => new Set(stagedNodes.map((n) => n.nodeId)),
        ],
        insertionIndex: [
            (s) => [s.expansionContext],
            (ctx): number => {
                if (!ctx) {
                    return 0
                }
                const { expansion, funnelStepCount } = ctx
                if (expansion.pathType === FunnelPathType.between) {
                    return expansion.stepIndex
                }
                if (expansion.pathType === FunnelPathType.before && expansion.stepIndex === 0) {
                    return 0
                }
                if (expansion.pathType === FunnelPathType.after) {
                    return funnelStepCount
                }
                return 0
            },
        ],
        sortedStagedNodes: [
            (s) => [s.stagedNodes],
            (stagedNodes): StagedNode[] =>
                [...stagedNodes].sort((a, b) => layerIndexFromNodeId(a.nodeId) - layerIndexFromNodeId(b.nodeId)),
        ],
        stagedNodeOptionalMap: [
            (s) => [s.stagedNodeOptional],
            (stagedNodeOptional): Map<string, boolean> => new Map(Object.entries(stagedNodeOptional)),
        ],
        newSeriesEntries: [
            (s) => [s.sortedStagedNodes, s.insertionIndex, s.stagedNodeOptional],
            (sortedNodes, insertionIndex, stagedNodeOptional): EventsNode[] => {
                const actionFilters = sortedNodes.map((node, i) => eventNameToActionFilter(node.eventName, i))
                const series = actionsAndEventsToSeries(
                    { events: actionFilters },
                    true,
                    MathAvailability.None
                ) as EventsNode[]
                return series.map((entry, i) => {
                    const nodeId = sortedNodes[i]?.nodeId
                    const isFirstFunnelStep = insertionIndex === 0 && i === 0
                    if (!isFirstFunnelStep && nodeId && stagedNodeOptional[nodeId]) {
                        return { ...entry, optionalInFunnel: true }
                    }
                    return entry
                })
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        saveChanges: async () => {
            try {
                const { activeInsight } = customerJourneysLogic.values
                if (!activeInsight?.query || !isInsightVizNode(activeInsight.query)) {
                    throw new Error('No active insight found')
                }

                const query = activeInsight.query as InsightVizNode<FunnelsQuery>
                const existingSeries = [...(query.source.series ?? [])]
                const { insertionIndex, newSeriesEntries } = values

                existingSeries.splice(insertionIndex, 0, ...newSeriesEntries)

                const updatedQuery: InsightVizNode<FunnelsQuery> = {
                    ...query,
                    source: {
                        ...query.source,
                        series: existingSeries,
                    },
                }

                await insightsApi.update(activeInsight.id, { query: updatedQuery })
                customerJourneysLogic.actions.loadActiveInsight()
                actions.saveChangesSuccess()
                lemonToast.success(
                    `Added ${newSeriesEntries.length} step${newSeriesEntries.length > 1 ? 's' : ''} to funnel`
                )
            } catch (e) {
                const message = e instanceof Error ? e.message : 'Failed to save changes'
                actions.saveChangesFailure(message)
                lemonToast.error(message)
            }
        },
    })),
])

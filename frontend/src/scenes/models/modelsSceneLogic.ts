import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { BehindScheduleModel, modelsBehindSchedule } from 'products/data_modeling/frontend/freshness'
import { NodeSuspensionApi } from 'products/data_modeling/frontend/generated/api.schemas'
import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import { buildAdjacencyMaps, traverseLineage } from 'products/data_modeling/frontend/lineage/lineageSearch'

import type { FeatureFlagsSet } from '../../lib/logic/featureFlagLogic'
import type { DataWarehouseSavedQuery } from '../../types'

export type ModelsSceneTab = 'overview' | 'models' | 'lineage' | 'data-quality'

const MODELS_SCENE_TABS: ModelsSceneTab[] = ['overview', 'models', 'lineage', 'data-quality']

function isModelsSceneTab(tab: unknown): tab is ModelsSceneTab {
    return typeof tab === 'string' && (MODELS_SCENE_TABS as string[]).includes(tab)
}

/** One row of the overview's attention table: a broken model, why, and what it holds up. */
export interface AttentionModel {
    node: DataModelingNode
    problem: 'Failed' | 'Suspended'
    reason: string | null
    downstreamCount: number
    skippedCount: number
}

export interface modelsSceneLogicValues {
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueriesLoading: boolean // dataWarehouseViewsLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    activeTab: ModelsSceneTab
    dataQualityTabEnabled: boolean
    nodes: DataModelingNode[] // lineageDataLogic
    nodesLoading: boolean // lineageDataLogic
    edges: DataModelingEdge[] // lineageDataLogic
    savedQueryIdToNodeId: Record<string, string>
    failingNodes: DataModelingNode[]
    suspendedNodes: DataModelingNode[]
    suspensionBySavedQueryId: Record<string, NodeSuspensionApi | undefined>
    attentionModels: AttentionModel[]
    behindSchedule: BehindScheduleModel[]
}

export interface modelsSceneLogicActions {
    loadDataWarehouseSavedQueries: () => any // dataWarehouseViewsLogic
    setActiveTab: (tab: ModelsSceneTab) => { tab: ModelsSceneTab }
}

export interface modelsSceneLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        savedQueryIdToNodeId: (nodes: DataModelingNode[]) => Record<string, string>
        failingNodes: (nodes: DataModelingNode[]) => DataModelingNode[]
        suspendedNodes: (nodes: DataModelingNode[]) => DataModelingNode[]
        suspensionBySavedQueryId: (nodes: DataModelingNode[]) => Record<string, NodeSuspensionApi | undefined>
        dataQualityTabEnabled: (featureFlags: FeatureFlagsSet) => boolean
        attentionModels: (
            failingNodes: DataModelingNode[],
            suspendedNodes: DataModelingNode[],
            edges: DataModelingEdge[],
            nodes: DataModelingNode[],
            savedQueries: DataWarehouseSavedQuery[]
        ) => AttentionModel[]
        behindSchedule: (nodes: DataModelingNode[], attentionModels: AttentionModel[]) => BehindScheduleModel[]
    }
}

export type modelsSceneLogicType = MakeLogicType<
    modelsSceneLogicValues,
    modelsSceneLogicActions,
    Record<string, any>,
    modelsSceneLogicMeta
>

export const modelsSceneLogic = kea<modelsSceneLogicType>([
    path(['scenes', 'models', 'modelsSceneLogic']),
    connect(() => ({
        values: [
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading'],
            featureFlagLogic,
            ['featureFlags'],
            lineageDataLogic,
            ['nodes', 'nodesLoading', 'edges'],
        ],
        actions: [dataWarehouseViewsLogic, ['loadDataWarehouseSavedQueries']],
    })),
    actions({
        setActiveTab: (tab: ModelsSceneTab) => ({ tab }),
    }),
    reducers({
        activeTab: [
            'overview' as ModelsSceneTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        savedQueryIdToNodeId: [
            (s) => [s.nodes],
            (nodes: DataModelingNode[]): Record<string, string> => {
                const map: Record<string, string> = {}
                for (const node of nodes) {
                    if (node.saved_query_id) {
                        map[node.saved_query_id] = node.id
                    }
                }
                return map
            },
        ],
        failingNodes: [
            (s) => [s.nodes],
            (nodes: DataModelingNode[]): DataModelingNode[] =>
                nodes.filter((node) => node.last_run_status === 'Failed'),
        ],
        // The saved-query list response omits `suspended`, so read it off the nodes.
        suspendedNodes: [
            (s) => [s.nodes],
            (nodes: DataModelingNode[]): DataModelingNode[] =>
                nodes.filter((node) => Object.keys(node.suspended ?? {}).length > 0),
        ],
        suspensionBySavedQueryId: [
            (s) => [s.suspendedNodes],
            (suspendedNodes: DataModelingNode[]): Record<string, NodeSuspensionApi | undefined> => {
                const map: Record<string, NodeSuspensionApi | undefined> = {}
                for (const node of suspendedNodes) {
                    if (node.saved_query_id) {
                        map[node.saved_query_id] = Object.values(node.suspended ?? {})[0]
                    }
                }
                return map
            },
        ],
        /**
         * What the overview leads with. Suspension outranks a failure because scheduled runs have
         * stopped entirely, and within each the widest blast radius comes first.
         */
        attentionModels: [
            (s) => [s.failingNodes, s.suspendedNodes, s.edges, s.nodes, s.dataWarehouseSavedQueries],
            (
                failingNodes: DataModelingNode[],
                suspendedNodes: DataModelingNode[],
                edges: DataModelingEdge[],
                nodes: DataModelingNode[],
                savedQueries: DataWarehouseSavedQuery[]
            ): AttentionModel[] => {
                const suspendedIds = new Set(suspendedNodes.map((node) => node.id))
                const affected = [...suspendedNodes, ...failingNodes.filter((node) => !suspendedIds.has(node.id))]
                if (affected.length === 0) {
                    return []
                }

                const errorBySavedQueryId: Record<string, string | null> = {}
                for (const query of savedQueries) {
                    errorBySavedQueryId[query.id] = query.latest_error ?? null
                }
                const nodeById: Record<string, DataModelingNode> = {}
                for (const node of nodes) {
                    nodeById[node.id] = node
                }
                const maps = buildAdjacencyMaps(edges)

                const rows = affected.map((node): AttentionModel => {
                    const suspension = Object.values(node.suspended ?? {})[0]
                    // The cone includes the node itself, which is not something it blocks.
                    const downstream = [...traverseLineage(node.id, maps, 'downstream')].filter((id) => id !== node.id)
                    return {
                        node,
                        problem: suspension ? 'Suspended' : 'Failed',
                        reason:
                            suspension?.reason ??
                            (node.saved_query_id ? errorBySavedQueryId[node.saved_query_id] : null) ??
                            null,
                        downstreamCount: downstream.length,
                        skippedCount: downstream.filter((id) => nodeById[id]?.last_run_status === 'Skipped').length,
                    }
                })

                return rows.sort((a, b) => {
                    if (a.problem !== b.problem) {
                        return a.problem === 'Suspended' ? -1 : 1
                    }
                    return b.downstreamCount - a.downstreamCount
                })
            },
        ],
        behindSchedule: [
            (s) => [s.nodes, s.attentionModels],
            (nodes: DataModelingNode[], attentionModels: AttentionModel[]): BehindScheduleModel[] => {
                // A failed or suspended model is behind as a consequence, and its own row
                // already says why, so reporting it here would only repeat the same problem.
                const reported = new Set(attentionModels.map((row) => row.node.id))
                return modelsBehindSchedule(nodes, Date.now()).filter((row) => !reported.has(row.node.id))
            },
        ],
        dataQualityTabEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS],
        ],
    }),
    urlToAction(({ actions, values }) => ({
        [urls.models()]: (_, searchParams) => {
            let tab: ModelsSceneTab = isModelsSceneTab(searchParams.tab) ? searchParams.tab : 'overview'
            if (tab === 'data-quality' && !values.dataQualityTabEnabled) {
                tab = 'overview'
            }
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataWarehouseSavedQueries()
    }),
])

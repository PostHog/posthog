import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { BehindScheduleModel, modelsBehindSchedule } from 'products/data_modeling/frontend/freshness'
import { NodeSuspensionApi } from 'products/data_modeling/frontend/generated/api.schemas'
import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import { buildAdjacencyMaps, traverseLineage } from 'products/data_modeling/frontend/lineage/lineageSearch'
import { servingSuspension } from 'products/data_modeling/frontend/suspension'

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
    receivedFeatureFlags: boolean // featureFlagLogic
    activeTab: ModelsSceneTab
    dataQualityTabEnabled: boolean
    nodes: DataModelingNode[] // lineageDataLogic
    nodesLoading: boolean // lineageDataLogic
    edges: DataModelingEdge[] // lineageDataLogic
    now: number
    savedQueryIdToNodeId: Record<string, string>
    failingNodes: DataModelingNode[]
    suspendedNodes: DataModelingNode[]
    suspensionBySavedQueryId: Record<string, NodeSuspensionApi | undefined>
    attentionModels: AttentionModel[]
    behindSchedule: BehindScheduleModel[]
}

export interface modelsSceneLogicActions {
    loadDataWarehouseSavedQueries: () => any // dataWarehouseViewsLogic
    setFeatureFlags: (flags: string[], variants: Record<string, boolean | string>) => any // featureFlagLogic
    setActiveTab: (tab: ModelsSceneTab) => { tab: ModelsSceneTab }
    setNow: (now: number) => { now: number }
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
        behindSchedule: (
            nodes: DataModelingNode[],
            attentionModels: AttentionModel[],
            now: number
        ) => BehindScheduleModel[]
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
            ['featureFlags', 'receivedFeatureFlags'],
            lineageDataLogic,
            ['nodes', 'nodesLoading', 'edges'],
        ],
        actions: [dataWarehouseViewsLogic, ['loadDataWarehouseSavedQueries'], featureFlagLogic, ['setFeatureFlags']],
    })),
    actions({
        setActiveTab: (tab: ModelsSceneTab) => ({ tab }),
        setNow: (now: number) => ({ now }),
    }),
    reducers({
        activeTab: [
            'overview' as ModelsSceneTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        now: [
            Date.now(),
            {
                setNow: (_, { now }) => now,
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
        /**
         * A marker only means scheduled runs stopped when it is on the serving engine and the team
         * enforces suspension. Detection runs for every team, so an unenforced marker is a record
         * of repeated failures while the schedule keeps firing.
         */
        suspendedNodes: [
            (s) => [s.nodes, s.featureFlags],
            (nodes: DataModelingNode[], featureFlags: FeatureFlagsSet): DataModelingNode[] => {
                if (!featureFlags[FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES]) {
                    return []
                }
                return nodes.filter((node) => servingSuspension(node.suspended))
            },
        ],
        suspensionBySavedQueryId: [
            (s) => [s.suspendedNodes],
            (suspendedNodes: DataModelingNode[]): Record<string, NodeSuspensionApi | undefined> => {
                const map: Record<string, NodeSuspensionApi | undefined> = {}
                for (const node of suspendedNodes) {
                    if (node.saved_query_id) {
                        map[node.saved_query_id] = servingSuspension(node.suspended)
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
            (s) => [s.failingNodes, s.suspendedNodes, s.edges, s.nodes],
            (
                failingNodes: DataModelingNode[],
                suspendedNodes: DataModelingNode[],
                edges: DataModelingEdge[],
                nodes: DataModelingNode[]
            ): AttentionModel[] => {
                const suspendedIds = new Set(suspendedNodes.map((node) => node.id))
                const affected = [...suspendedNodes, ...failingNodes.filter((node) => !suspendedIds.has(node.id))]
                if (affected.length === 0) {
                    return []
                }

                const nodeById: Record<string, DataModelingNode> = {}
                for (const node of nodes) {
                    nodeById[node.id] = node
                }
                const maps = buildAdjacencyMaps(edges)

                const rows = affected.map((node): AttentionModel => {
                    const suspension = servingSuspension(node.suspended)
                    // The cone includes the node itself, which is not something it blocks.
                    const downstream = [...traverseLineage(node.id, maps, 'downstream')].filter((id) => id !== node.id)
                    return {
                        node,
                        problem: suspension ? 'Suspended' : 'Failed',
                        reason: suspension?.reason ?? node.last_run_error ?? null,
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
            (s) => [s.nodes, s.attentionModels, s.now],
            (nodes: DataModelingNode[], attentionModels: AttentionModel[], now: number): BehindScheduleModel[] => {
                // A failed or suspended model is behind as a consequence, and its own row
                // already says why, so reporting it here would only repeat the same problem.
                const reported = new Set(attentionModels.map((row) => row.node.id))
                return modelsBehindSchedule(nodes, now).filter((row) => !reported.has(row.node.id))
            },
        ],
        dataQualityTabEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS],
        ],
    }),
    listeners(({ actions }) => ({
        setFeatureFlags: ({ variants }) => {
            if (router.values.searchParams.tab === 'data-quality') {
                actions.setActiveTab(variants[FEATURE_FLAGS.DATA_QUALITY_CHECKS] ? 'data-quality' : 'overview')
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.models()]: (_, searchParams) => {
            let tab: ModelsSceneTab = isModelsSceneTab(searchParams.tab) ? searchParams.tab : 'overview'
            if (tab === 'data-quality' && !values.receivedFeatureFlags) {
                return
            }
            if (tab === 'data-quality' && !values.dataQualityTabEnabled) {
                tab = 'overview'
            }
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadDataWarehouseSavedQueries()
        actions.setNow(Date.now())
        cache.disposables.add(() => {
            const intervalId = window.setInterval(() => actions.setNow(Date.now()), 60_000)
            return () => window.clearInterval(intervalId)
        })
    }),
])

import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, DataModelingEdge, DataModelingJob, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import type { nodeDetailSceneLogicType } from './nodeDetailSceneLogicType'

export interface NodeDetailSceneLogicProps {
    id: string
}

export interface LineageGraphData {
    /** DataModelingNode objects in the subgraph (ancestors + current + descendants) */
    nodes: DataModelingNode[]
    /** Edges between nodes in the subgraph */
    edges: DataModelingEdge[]
    /** The current node's ID */
    currentNodeId: string
}

export const nodeDetailSceneLogic = kea<nodeDetailSceneLogicType>([
    props({} as NodeDetailSceneLogicProps),
    key((props) => props.id),
    path((key) => ['scenes', 'models', 'nodeDetailSceneLogic', key]),
    connect({
        actions: [dataWarehouseViewsLogic, ['updateDataWarehouseSavedQuerySuccess']],
    }),
    actions({
        updateNodeDescription: (description: string) => ({ description }),
        setJobsOffset: (offset: number) => ({ offset }),
        openLineageModal: true,
        closeLineageModal: true,
    }),
    reducers({
        jobsOffset: [
            0 as number,
            {
                setJobsOffset: (_, { offset }) => offset,
            },
        ],
        lineageModalOpen: [
            false,
            {
                openLineageModal: () => true,
                closeLineageModal: () => false,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        node: {
            __default: null as DataModelingNode | null,
            loadNode: async () => {
                return await api.dataModelingNodes.get(props.id)
            },
            updateNodeDescription: async ({ description }) => {
                const updated = await api.dataModelingNodes.update(props.id, { description })
                return updated
            },
        },
        savedQuery: {
            __default: null as DataWarehouseSavedQuery | null,
            loadSavedQuery: async () => {
                const node = values.node
                if (!node?.saved_query_id) {
                    return null
                }
                return await api.dataWarehouseSavedQueries.get(node.saved_query_id)
            },
        },
        materializationJobs: {
            __default: null as PaginatedResponse<DataModelingJob> | null,
            loadMaterializationJobs: async () => {
                const savedQuery = values.savedQuery
                if (!savedQuery) {
                    return null
                }
                return await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                    savedQuery.id,
                    10,
                    values.jobsOffset
                )
            },
        },
        lineageGraph: {
            __default: null as LineageGraphData | null,
            loadLineageGraph: async () => {
                const node = values.node
                if (!node) {
                    return null
                }
                const { nodes, edges } = await api.dataModelingNodes.lineage(node.id)
                return { nodes, edges, currentNodeId: node.id }
            },
        },
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.node],
            (node: DataModelingNode | null): Breadcrumb[] => [
                {
                    key: 'Models',
                    name: 'Models',
                    path: urls.models(),
                },
                {
                    key: ['NodeDetail', node?.id || 'loading'],
                    name: node?.name || 'Loading...',
                },
            ],
        ],
        nodeType: [(s) => [s.node], (node: DataModelingNode | null) => node?.type ?? null],
        hasMaterialization: [
            (s) => [s.node, s.savedQuery],
            (node: DataModelingNode | null, savedQuery: DataWarehouseSavedQuery | null): boolean =>
                (node?.type === 'matview' || node?.type === 'endpoint') && !!savedQuery?.is_materialized,
        ],
        effectiveLastRunAt: [
            (s) => [s.node, s.materializationJobs],
            (node: DataModelingNode | null, jobs: PaginatedResponse<DataModelingJob> | null): string | null => {
                if (node?.last_run_at) {
                    return node.last_run_at
                }
                // Fall back to the most recent completed job
                const completedJob = jobs?.results?.find((j) => j.status === 'Completed')
                return completedJob?.last_run_at ?? null
            },
        ],
        effectiveLastRunStatus: [
            (s) => [s.node, s.materializationJobs],
            (node: DataModelingNode | null, jobs: PaginatedResponse<DataModelingJob> | null): string | null =>
                node?.last_run_status || jobs?.results?.[0]?.status || null,
        ],
    }),
    listeners(({ actions, values }) => ({
        loadNodeSuccess: () => {
            const node = values.node
            if (node?.saved_query_id) {
                actions.loadSavedQuery()
            }
            actions.loadLineageGraph()
        },
        loadSavedQuerySuccess: () => {
            if (values.hasMaterialization) {
                actions.loadMaterializationJobs()
            }
        },
        setJobsOffset: () => {
            actions.loadMaterializationJobs()
        },
        updateDataWarehouseSavedQuerySuccess: () => {
            if (values.node?.saved_query_id) {
                actions.loadSavedQuery()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNode()
    }),
])

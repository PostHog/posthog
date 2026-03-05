import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, DataModelingJob, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import type { nodeDetailSceneLogicType } from './nodeDetailSceneLogicType'

export interface LineageGraphPair {
    compact: { nodes: any[]; edges: any[] }
    full: { nodes: any[]; edges: any[] }
}

export interface NodeDetailSceneLogicProps {
    id: string
}

export const nodeDetailSceneLogic = kea<nodeDetailSceneLogicType>([
    props({} as NodeDetailSceneLogicProps),
    path(['scenes', 'models', 'nodeDetailSceneLogic']),
    key((props: NodeDetailSceneLogicProps) => props.id),
    loaders(({ props }) => ({
        node: [
            null as DataModelingNode | null,
            {
                loadNode: async () => {
                    return await api.dataModelingNodes.get(props.id)
                },
            },
        ],
        savedQuery: [
            null as DataWarehouseSavedQuery | null,
            {
                loadSavedQuery: async (savedQueryId: string) => {
                    return await api.dataWarehouseSavedQueries.get(savedQueryId)
                },
            },
        ],
        materializationJobs: [
            null as PaginatedResponse<DataModelingJob> | null,
            {
                loadMaterializationJobs: async (savedQueryId: string) => {
                    return await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(savedQueryId, 10, 0)
                },
                loadMaterializationJobsFromUrl: async (url: string) => {
                    return await api.get(url)
                },
            },
        ],
    })),
    actions({
        openQueryModal: true,
        closeQueryModal: true,
        updateNodeDescription: (description: string) => ({ description }),
    }),
    reducers({
        queryModalOpen: [
            false,
            {
                openQueryModal: () => true,
                closeQueryModal: () => false,
            },
        ],
    }),
    selectors({
        nodeType: [(s) => [s.node], (node: DataModelingNode | null) => node?.type ?? null],
        breadcrumbs: [
            (s) => [s.node],
            (node: DataModelingNode | null): Breadcrumb[] => [
                {
                    key: Scene.Models,
                    name: 'Models',
                    path: urls.models(),
                },
                {
                    key: [Scene.NodeDetail, node?.id || 'loading'],
                    name: node?.name || 'Loading...',
                },
            ],
        ],
        latestRowCount: [
            (s) => [s.materializationJobs],
            (jobs: PaginatedResponse<DataModelingJob> | null): number | null => {
                const completed = jobs?.results?.find((j) => j.status === 'Completed')
                return completed?.rows_materialized ?? null
            },
        ],
        latestJobStatus: [
            (s) => [s.materializationJobs],
            (jobs: PaginatedResponse<DataModelingJob> | null): string | null => {
                const latest = jobs?.results?.[0]
                return latest?.status ?? null
            },
        ],
    }),
    listeners(({ actions }) => ({
        loadNodeSuccess: ({ node }) => {
            if (node?.saved_query_id) {
                actions.loadSavedQuery(node.saved_query_id)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNode()
    }),
])

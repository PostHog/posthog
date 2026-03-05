import { afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import type { nodeDetailSceneLogicType } from './nodeDetailSceneLogicType'

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
    })),
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

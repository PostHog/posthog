import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { Node } from 'scenes/data-model/types'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataWarehouseSavedQuery } from '~/types'

import { multitabEditorLogic } from '../multitabEditorLogic'
import type { lineageTabLogicType } from './lineageTabLogicType'

export interface LineageTabLogicProps {
    codeEditorKey: string
}

export const lineageTabLogic = kea<lineageTabLogicType>([
    path(['data-warehouse', 'editor', 'outputPaneTabs', 'lineageTabLogic']),
    props({} as LineageTabLogicProps),
    key((props) => props.codeEditorKey),
    actions({
        loadNodes: true,
        traverseAncestors: (viewId: DataWarehouseSavedQuery['id'], level: number) => ({ viewId, level }),
        setNodes: (nodes: Record<string, Node>) => ({ nodes }),
    }),
    connect((props: LineageTabLogicProps) => ({
        values: [
            multitabEditorLogic({ key: props.codeEditorKey }),
            ['metadata'],
            databaseTableListLogic,
            ['posthogTablesMap', 'viewsMapById', 'dataWarehouseTablesMapById'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueryMap'],
        ],
        actions: [
            multitabEditorLogic({ key: props.codeEditorKey }),
            ['runQuery'],
            dataWarehouseViewsLogic,
            ['loadDataWarehouseSavedQueries'],
        ],
    })),
    reducers({
        nodeMap: [
            {} as Record<string, Node>,
            {
                setNodes: (_, { nodes }) => nodes,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadNodes: async () => {
            const nodes: Record<string, Node> = {}

            const traverseAncestors = async (viewId: DataWarehouseSavedQuery['id'], level: number): Promise<void> => {
                if (!nodes[viewId]?.savedQueryId) {
                    return
                }

                const result = await api.dataWarehouseSavedQueries.ancestors(viewId, level)
                for (const ancestor of result.ancestors) {
                    nodes[ancestor] = {
                        nodeId: ancestor,
                        name:
                            values.viewsMapById[ancestor]?.name ||
                            values.dataWarehouseTablesMapById[ancestor]?.name ||
                            ancestor,
                        savedQueryId: values.viewsMapById[ancestor]?.id,
                        leaf: [...(nodes[ancestor]?.leaf || []), viewId],
                    }
                    await traverseAncestors(ancestor, 1)
                }
            }

            values.sources.forEach((source) => {
                if (!source) {
                    return
                }
                nodes[source] = {
                    nodeId: source,
                    name: source,
                    savedQueryId: undefined,
                    leaf: [],
                }
            })

            for (const view of values.views) {
                if (!view) {
                    continue
                }
                nodes[view.id] = {
                    nodeId: view.id,
                    name: view.name,
                    savedQueryId: view.id,
                    leaf: [],
                }
                await traverseAncestors(view.id, 1)
            }
            actions.setNodes(nodes)
        },
    })),
    subscriptions(({ actions }) => ({
        metadata: () => {
            actions.loadNodes()
        },
    })),
    selectors({
        views: [
            (s) => [s.metadata, s.dataWarehouseSavedQueryMap],
            (metadata, dataWarehouseSavedQueryMap) => {
                if (!metadata) {
                    return []
                }
                return (
                    metadata.table_names
                        ?.map((table_name: string) => {
                            const view = dataWarehouseSavedQueryMap[table_name]
                            if (view) {
                                return view
                            }
                        })
                        .filter(Boolean) || []
                )
            },
        ],
        sources: [
            (s) => [s.metadata, s.dataWarehouseSavedQueryMap],
            (metadata, dataWarehouseSavedQueryMap) => {
                if (!metadata) {
                    return []
                }
                return (
                    metadata.table_names
                        ?.map((table_name: string) => {
                            const view = dataWarehouseSavedQueryMap[table_name]
                            if (!view) {
                                return table_name
                            }
                        })
                        .filter(Boolean) || []
                )
            },
        ],
        allNodes: [(s) => [s.nodeMap], (nodeMap) => [...Object.values(nodeMap)]],
    }),
    events(({ cache, actions }) => ({
        afterMount: () => {
            if (!cache.pollingInterval) {
                cache.pollingInterval = setInterval(() => actions.loadDataWarehouseSavedQueries(), 10000)
            }
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])

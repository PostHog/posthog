import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
        actions: [multitabEditorLogic({ key: props.codeEditorKey }), ['runQuery']],
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
        runQuery: () => {
            actions.loadNodes()
        },
        loadNodes: () => {
            values.views.forEach((view) => {
                if (!view) {
                    return
                }
                actions.setNodes({
                    ...values.nodeMap,
                    [view.id]: {
                        nodeId: view.id,
                        name: view.name,
                        savedQueryId: view.id,
                        leaf: [],
                    },
                })
                actions.traverseAncestors(view.id, 1)
            })
        },
        traverseAncestors: async ({ viewId, level }) => {
            const result = await api.dataWarehouseSavedQueries.ancestors(viewId, level)

            result.ancestors.forEach((ancestor) => {
                actions.setNodes({
                    ...values.nodeMap,
                    [ancestor]: {
                        nodeId: ancestor,
                        name:
                            values.viewsMapById[ancestor]?.name ||
                            values.dataWarehouseTablesMapById[ancestor]?.name ||
                            ancestor,
                        savedQueryId: values.viewsMapById[ancestor]?.id,
                        leaf: [...(values.nodeMap[ancestor]?.leaf || []), viewId],
                    },
                })
                actions.traverseAncestors(ancestor, 1)
            })
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
])

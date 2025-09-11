import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery } from '~/types'

import type { dataModelSceneLogicType } from './dataModelSceneLogicType'
import { Node } from './types'

export const dataModelSceneLogic = kea<dataModelSceneLogicType>([
    path(['scenes', 'data-model', 'dataModelSceneLogic']),
    connect(() => ({
        values: [databaseTableListLogic, ['posthogTablesMap', 'viewsMapById', 'dataWarehouseTablesMapById']],
    })),
    actions({
        traverseAncestors: (viewId: DataWarehouseSavedQuery['id'], level: number) => ({ viewId, level }),
        setNodes: (nodes: Record<string, Node>) => ({ nodes }),
    }),
    reducers({
        nodeMap: [
            {} as Record<string, Node>,
            {
                setNodes: (_, { nodes }) => nodes,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        traverseAncestors: async ({ viewId, level }) => {
            const result = await api.dataWarehouseSavedQueries.ancestors(viewId, level)

            if (!values.nodeMap[viewId]?.savedQueryId) {
                return
            }

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
        personFields: [(s) => [s.posthogTablesMap], (posthogTablesMap) => posthogTablesMap['persons']?.fields || []],
        simplifiedPersonFields: [
            (s) => [s.personFields],
            (personFields) =>
                Object.entries(personFields)
                    .filter(([_, data]) => data.type != 'view' && !(data.type == 'lazy_table' && data.name !== 'pdi'))
                    .map(([column, data]) => ({ column, type: data.type })),
        ],
        joinedFields: [
            (s) => [s.personFields],
            (personFields) =>
                Object.entries(personFields)
                    .filter(([_, data]) => data.type == 'view' || (data.type == 'lazy_table' && data.name !== 'pdi'))
                    .map(([_, data]) => data),
        ],
        joinedFieldsAsNodes: [
            (s) => [s.joinedFields],
            (joinedFields) =>
                joinedFields.map((field) => ({
                    nodeId: field.name,
                    type: 'view',
                    table: field.name,
                })) || [],
        ],
        allNodes: [(s) => [s.nodeMap], (nodeMap) => Object.values(nodeMap)],
    }),
    subscriptions(({ actions, values }) => ({
        joinedFields: (joinedFields) => {
            joinedFields.forEach((field: DatabaseSchemaTable) => {
                actions.setNodes({
                    ...values.nodeMap,
                    [field.id]: {
                        nodeId: field.id,
                        name:
                            values.viewsMapById[field.id]?.name ||
                            values.dataWarehouseTablesMapById[field.id]?.name ||
                            field.id,
                        savedQueryId: values.viewsMapById[field.id]?.id,
                        leaf: [`${field.name}_joined`],
                    },
                })
                field.id && actions.traverseAncestors(field.id, 1)
            })
        },
    })),
])

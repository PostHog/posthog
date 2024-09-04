import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSchemaTable } from '~/queries/schema'
import { DataWarehouseSavedQuery } from '~/types'

import type { dataModelSceneLogicType } from './dataModelSceneLogicType'
import { Node } from './types'

export const dataModelSceneLogic = kea<dataModelSceneLogicType>([
    path(['scenes', 'data-model', 'dataModelSceneLogic']),
    connect(() => ({
        values: [databaseTableListLogic, ['posthogTablesMap', 'viewsMapById']],
    })),
    actions({
        traverseAncestors: (viewId: DataWarehouseSavedQuery['id']) => ({ viewId }),
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
        traverseAncestors: async ({ viewId }) => {
            const result = await api.dataWarehouseSavedQueries.ancestors(viewId)

            result.ancestors.forEach((ancestor) => {
                actions.setNodes({
                    ...values.nodeMap,
                    [ancestor]: {
                        nodeId: ancestor,
                        name: values.viewsMapById[ancestor]?.name || ancestor,
                        leaf: [...(values.nodeMap[ancestor]?.leaf || []), viewId],
                    },
                })
            })
        },
    })),
    selectors({
        personFields: [(s) => [s.posthogTablesMap], (posthogTablesMap) => posthogTablesMap['persons']?.fields || []],
        simplifiedPersonFields: [
            (s) => [s.personFields],
            (personFields) =>
                Object.entries(personFields)
                    .filter(([_, data]) => data.type != 'view')
                    .map(([column, data]) => ({ column, type: data.type })),
        ],
        joinedFields: [
            (s) => [s.personFields],
            (personFields) =>
                Object.entries(personFields)
                    .filter(([_, data]) => data.type == 'view')
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
        allNodes: [
            (s) => [s.nodeMap],
            (nodeMap) => [
                {
                    nodeId: 'posthog',
                    name: 'PostHog',
                    leaf: ['schema'],
                },
                ...Object.values(nodeMap),
            ],
        ],
    }),
    subscriptions(({ actions, values }) => ({
        joinedFields: (joinedFields) => {
            joinedFields.forEach((field: DatabaseSchemaTable) => {
                actions.setNodes({
                    ...values.nodeMap,
                    [field.id]: {
                        nodeId: field.id,
                        name: values.viewsMapById[field.id]?.name || field.id,
                        leaf: [field.name],
                    },
                })
                actions.traverseAncestors(field.id)
            })
        },
    })),
])

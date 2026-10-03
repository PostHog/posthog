import { MakeLogicType, actions, kea, key, path, props, reducers, selectors } from 'kea'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { LineageSelection, LineageSelectionMode, scopeLineage } from './lineageSelection'

export interface LineageScopeLogicProps {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
    variant: string
    direction: string
}

export interface lineageScopeLogicValues {
    scope: LineageSelection | null
    scoped: { nodes: DataModelingNode[]; edges: DataModelingEdge[] } | null
}

export interface lineageScopeLogicActions {
    showOnly: (
        nodeId: string,
        mode: LineageSelectionMode
    ) => {
        nodeId: string
        mode: LineageSelectionMode
    }
    showAll: () => Record<string, never>
}

export type lineageScopeLogicType = MakeLogicType<
    lineageScopeLogicValues,
    lineageScopeLogicActions,
    LineageScopeLogicProps,
    { key: string }
>

// Keyed without node ids, unlike lineageGraphLogic: scoping changes the node set, and a key that
// followed it would build a new instance and drop the scope.
export const lineageScopeLogic = kea<lineageScopeLogicType>([
    path(['products', 'data_modeling', 'frontend', 'lineage', 'lineageScopeLogic']),
    props({} as LineageScopeLogicProps),
    key((props) => `${props.variant}-${props.direction}`),
    actions({
        showOnly: (nodeId: string, mode: LineageSelectionMode) => ({ nodeId, mode }),
        showAll: true,
    }),
    reducers({
        scope: [
            null as LineageSelection | null,
            {
                showOnly: (_, { nodeId, mode }) => ({ nodeId, mode }),
                showAll: () => null,
            },
        ],
    }),
    selectors({
        scoped: [(s, p) => [s.scope, p.nodes, p.edges], (scope, nodes, edges) => scopeLineage(nodes, edges, scope)],
    }),
])

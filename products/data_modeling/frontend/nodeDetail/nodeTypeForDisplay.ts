import type { DataModelingNode, DataModelingNodeType, DataWarehouseSavedQuery } from '~/types'

export function nodeTypeForDisplay(
    node: DataModelingNode | null,
    savedQuery: DataWarehouseSavedQuery | null
): DataModelingNodeType | undefined {
    if (node?.type !== 'view' && node?.type !== 'matview') {
        return node?.type
    }
    if (!savedQuery) {
        return node.type
    }
    return savedQuery.is_materialized ? 'matview' : 'view'
}

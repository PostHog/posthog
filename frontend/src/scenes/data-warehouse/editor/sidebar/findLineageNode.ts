import { DataModelingNode } from '~/types'

export type LineageTarget =
    | { kind: 'saved_query'; savedQueryId: string }
    | { kind: 'warehouse_table'; warehouseTableId: string }
    | { kind: 'posthog_table'; tableName: string }

export function findLineageNode(nodes: DataModelingNode[], target: LineageTarget): DataModelingNode | undefined {
    switch (target.kind) {
        case 'saved_query':
            return nodes.find((node) => node.saved_query_id === target.savedQueryId)
        case 'warehouse_table':
            return nodes.find((node) => node.type === 'table' && node.warehouse_table_id === target.warehouseTableId)
        case 'posthog_table':
            return nodes.find(
                (node) => node.type === 'table' && node.origin === 'posthog' && node.name === target.tableName
            )
    }
}

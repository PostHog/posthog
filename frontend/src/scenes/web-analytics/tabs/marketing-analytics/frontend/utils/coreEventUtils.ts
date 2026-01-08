import { CoreEvent, DataWarehouseNode, NodeKind } from '~/queries/schema/schema-general'

export function getGoalTypeLabel(goal: CoreEvent): string {
    switch (goal.filter.kind) {
        case NodeKind.EventsNode:
            return 'Event'
        case NodeKind.ActionsNode:
            return 'Action'
        case NodeKind.DataWarehouseNode:
            return 'Data warehouse'
        default:
            return 'Unknown'
    }
}

export function getGoalFilterSummary(goal: CoreEvent): string {
    const filter = goal.filter
    switch (filter.kind) {
        case NodeKind.EventsNode:
            return filter.event || 'All events'
        case NodeKind.ActionsNode:
            return filter.name || `Action #${filter.id}`
        case NodeKind.DataWarehouseNode:
            return filter.table_name || 'Unknown table'
        default:
            return 'Unknown'
    }
}

export interface DataWarehouseTable {
    name: string
    fields: Record<string, { hogql_value: string }>
}

export function getTableColumns(goal: CoreEvent, dataWarehouseTables: DataWarehouseTable[]): string[] {
    if (goal.filter.kind !== NodeKind.DataWarehouseNode) {
        return []
    }
    const filter = goal.filter as DataWarehouseNode
    const table = dataWarehouseTables?.find((t) => t.name === filter.table_name)
    if (!table?.fields) {
        return []
    }
    return Object.keys(table.fields).map((field) => table.fields[field].hogql_value)
}

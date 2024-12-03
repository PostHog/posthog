import { DatabaseSchemaField, DataVisualizationNode, NodeKind } from '~/queries/schema'

export const defaultQuery = (table: string, columns: DatabaseSchemaField[]): DataVisualizationNode => {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            // TODO: Use `hogql` tag?
            query: `SELECT ${columns
                .filter(({ table, fields, chain, schema_valid }) => !table && !fields && !chain && schema_valid)
                .map(({ name }) => name)} FROM ${table === 'numbers' ? 'numbers(0, 10)' : table} LIMIT 100`,
        },
    }
}

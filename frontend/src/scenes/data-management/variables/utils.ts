import { DataVisualizationNode, HogQLVariable } from '~/queries/schema/schema-general'
import { QueryBasedInsightModel } from '~/types'

/**
 * Type guard to check if a query is a DataVisualizationNode
 */
export function isDataVisualizationNode(query: any): query is DataVisualizationNode {
    return query?.kind === 'DataVisualizationNode'
}

/**
 * Check if an insight uses a specific variable
 */
export function insightUsesVariable(insight: QueryBasedInsightModel, variableId: string): boolean {
    if (!isDataVisualizationNode(insight.query)) {
        return false
    }

    const variables = insight.query.source?.variables
    if (!variables) {
        return false
    }

    return Object.values(variables).some((v: HogQLVariable) => v.variableId === variableId)
}

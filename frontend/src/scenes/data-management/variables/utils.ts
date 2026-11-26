import { Variable, VariableType } from '~/queries/nodes/DataVisualization/types'
import { DataVisualizationNode, HogQLVariable } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

/**
 * Type guard to check if a query is a DataVisualizationNode
 */
export function isDataVisualizationNode(query: any): query is DataVisualizationNode {
    return query?.kind === 'DataVisualizationNode'
}

/**
 * Check if an insight uses a specific variable
 */
export function insightUsesVariable(insight: InsightModel, variableId: string): boolean {
    if (!isDataVisualizationNode(insight.query)) {
        return false
    }

    const variables = insight.query.source?.variables
    if (!variables) {
        return false
    }

    return Object.values(variables).some((v: HogQLVariable) => v.variableId === variableId)
}

/**
 * Build a full variable from the edit page's partial form values, so the type-specific fields can bind to it
 */
export function toFormVariable(variableForm: Partial<Variable>, variableType: VariableType): Variable {
    return {
        id: '',
        name: '',
        code_name: '',
        default_value: '',
        ...variableForm,
        type: variableType,
        ...(variableType === 'List' && { values: 'values' in variableForm ? (variableForm.values ?? []) : [] }),
    } as Variable
}

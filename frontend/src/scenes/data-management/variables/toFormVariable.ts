import { Variable, VariableType } from '~/queries/nodes/DataVisualization/types'

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

import { useActions, useValues } from 'kea'

import { ListVariable } from '../../types'
import { VariableOption, getStaticVariableOptions, getValuesQueryKey, variableValuesLogic } from './variableValuesLogic'

export interface ListVariableOptions {
    options: VariableOption[]
    error: string | null
    loading: boolean
    reload: () => void
}

export function useListVariableOptions(variable: ListVariable, loadOnMount: boolean): ListVariableOptions {
    const logic = variableValuesLogic({ variable, loadOnMount })
    const { loadVariableOptions } = useActions(logic)
    const { requestedValuesQueryKey, variableOptions, variableOptionsError, variableOptionsLoading } = useValues(logic)
    const isCurrentQuery = requestedValuesQueryKey === getValuesQueryKey(variable)

    return {
        options:
            variable.values_query == null ? getStaticVariableOptions(variable) : isCurrentQuery ? variableOptions : [],
        error: isCurrentQuery ? variableOptionsError : null,
        loading: variableOptionsLoading,
        reload: () => loadVariableOptions(variable),
    }
}

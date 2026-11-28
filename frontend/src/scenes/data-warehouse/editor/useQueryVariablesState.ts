import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { Variable, VariableType } from '~/queries/nodes/DataVisualization/types'

import { sqlEditorLogic } from './sqlEditorLogic'

export const NEW_VARIABLE_TYPES: VariableType[] = ['String', 'Number', 'Boolean', 'List', 'Date']

export const variableCode = (variable: Variable): string => `{variables.${variable.code_name}}`

export interface QueryVariablesState {
    /** False where the editor is read-only, so variables can't be set from it. */
    showEditingUI: boolean
    loading: boolean
    searchTerm: string
    setSearchTerm: (searchTerm: string) => void
    /** Variables the query references. Their values can be set here. */
    usedInQuery: Variable[]
    /** Variables the query no longer references, whose values are kept until they are removed. */
    unusedWithValues: Variable[]
    /** Every other variable in the project. Picking one inserts it into the query. */
    other: Variable[]
    setValue: (variable: Variable, value: any, isNull: boolean) => void
    insert: (variable: Variable) => void
    remove: (variable: Variable) => void
    copyCode: (variable: Variable) => void
    edit: (variable: Variable) => void
    create: (type: VariableType) => void
}

/** The SQL editor's variables and what each variable action does, shared by the Lemon menu and the quill panel. */
export function useQueryVariablesState(): QueryVariablesState {
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { variablesLoading, variablesUsedInQuery, variablesNotInQuery, searchTerm, internalSelectedVariables } =
        useValues(variablesLogic)
    const { setSearchTerm, updateVariableValue, addVariable, removeVariable } = useActions(variablesLogic)
    const { openNewVariableModal, openExistingVariableModal } = useActions(variableModalLogic)
    const { insertTextAtCursor } = useActions(sqlEditorLogic)

    const selectedVariableIds = new Set(internalSelectedVariables.map((variable) => variable.variableId))

    return {
        showEditingUI,
        loading: variablesLoading,
        searchTerm,
        setSearchTerm,
        usedInQuery: variablesUsedInQuery,
        unusedWithValues: variablesNotInQuery.filter((variable) => selectedVariableIds.has(variable.id)),
        other: variablesNotInQuery.filter((variable) => !selectedVariableIds.has(variable.id)),
        setValue: (variable, value, isNull) => {
            if (!selectedVariableIds.has(variable.id)) {
                addVariable({ variableId: variable.id, code_name: variable.code_name })
            }
            updateVariableValue(variable.id, value, isNull)
        },
        insert: (variable) => insertTextAtCursor(variableCode(variable)),
        remove: (variable) => {
            removeVariable(variable.id)
            posthog.capture('sql unused variable removed')
        },
        copyCode: (variable) => void copyToClipboard(variableCode(variable), 'variable SQL'),
        edit: (variable) => openExistingVariableModal(variable),
        create: (type) => openNewVariableModal(type),
    }
}

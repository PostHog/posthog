import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { Variable } from '~/queries/nodes/DataVisualization/types'

import type { sqlVariablesLogicType } from './sqlVariablesLogicType'

export const sqlVariablesLogic = kea<sqlVariablesLogicType>([
    path(['scenes', 'data-management', 'variables', 'sqlVariablesLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        deleteVariable: (variableId: string) => ({ variableId }),
    }),
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    loaders(({ values }) => ({
        variables: [
            [] as Variable[],
            {
                loadVariables: async () => {
                    const response = await api.insightVariables.list()
                    return response.results
                },
                deleteVariableSuccess: async ({ variableId }: { variableId: string }) => {
                    try {
                        await api.insightVariables.delete(variableId)
                        lemonToast.success('Variable deleted')
                        return values.variables.filter((variable: Variable) => variable.id !== variableId)
                    } catch {
                        lemonToast.error('Failed to delete variable')
                        return values.variables
                    }
                },
            },
        ],
    })),
    selectors({
        filteredVariables: [
            (s) => [s.variables, s.searchTerm],
            (variables: Variable[], searchTerm: string): Variable[] => {
                if (!searchTerm) {
                    return variables
                }
                const lowerSearchTerm = searchTerm.toLowerCase()
                return variables.filter(
                    (variable: Variable) =>
                        variable.name.toLowerCase().includes(lowerSearchTerm) ||
                        variable.code_name.toLowerCase().includes(lowerSearchTerm)
                )
            },
        ],
    }),
    listeners(({ actions }) => ({
        deleteVariable: ({ variableId }: { variableId: string }) => {
            actions.deleteVariableSuccess({ variableId })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadVariables()
    }),
])

import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { BooleanVariable, ListVariable, NumberVariable, StringVariable, Variable, VariableType } from '../../types'
import type { addVariableLogicType } from './addVariableLogicType'

const DEFAULT_VARIABLE: StringVariable = {
    id: '',
    type: 'String',
    name: '',
    default_value: '',
}

export const addVariableLogic = kea<addVariableLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableLogic']),
    actions({
        openModal: (variableType: VariableType) => ({ variableType }),
        closeModal: true,
        updateVariable: (variable: Variable) => ({ variable }),
    }),
    reducers({
        variableType: [
            'string' as VariableType,
            {
                openModal: (_, { variableType }) => variableType,
            },
        ],
        isModalOpen: [
            false as boolean,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        variable: [
            DEFAULT_VARIABLE as Variable,
            {
                openModal: (_, { variableType }) => {
                    if (variableType === 'String') {
                        return {
                            id: '',
                            type: 'String',
                            name: '',
                            default_value: '',
                        } as StringVariable
                    }

                    if (variableType === 'Number') {
                        return {
                            id: '',
                            type: 'Number',
                            name: '',
                            default_value: 0,
                        } as NumberVariable
                    }

                    if (variableType === 'Boolean') {
                        return {
                            id: '',
                            type: 'Boolean',
                            name: '',
                            default_value: false,
                        } as BooleanVariable
                    }

                    if (variableType === 'List') {
                        return {
                            id: '',
                            type: 'List',
                            name: '',
                            values: [],
                            default_value: '',
                        } as ListVariable
                    }

                    throw new Error(`Unsupported variable type ${variableType}`)
                },
                updateVariable: (state, { variable }) => ({ ...state, ...variable }),
                closeModal: () => DEFAULT_VARIABLE,
            },
        ],
    }),
    loaders(({ values }) => ({
        savedVariable: [
            null as null | Variable,
            {
                save: async () => {
                    return await api.insightVariables.create(values.variable)
                },
            },
        ],
    })),
])

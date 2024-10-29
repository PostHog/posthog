import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import api, { ApiError } from 'lib/api'

import { BooleanVariable, ListVariable, NumberVariable, StringVariable, Variable, VariableType } from '../../types'
import { variableDataLogic } from './variableDataLogic'
import type { variableModalLogicType } from './variableModalLogicType'
import { variablesLogic } from './variablesLogic'

const DEFAULT_VARIABLE: StringVariable = {
    id: '',
    type: 'String',
    name: '',
    default_value: '',
    code_name: '',
}

export interface AddVariableLogicProps {
    key: string
}

export const variableModalLogic = kea<variableModalLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableLogic']),
    props({ key: '' } as AddVariableLogicProps),
    key((props) => props.key),
    connect({
        actions: [variableDataLogic, ['getVariables'], variablesLogic, ['addVariable']],
    }),
    actions({
        openNewVariableModal: (variableType: VariableType) => ({ variableType }),
        openExistingVariableModal: (variable: Variable) => ({ variable }),
        closeModal: true,
        updateVariable: (variable: Variable) => ({ variable }),
        save: true,
    }),
    reducers({
        modalType: [
            'new' as 'new' | 'existing',
            {
                openNewVariableModal: () => 'new',
                openExistingVariableModal: () => 'existing',
            },
        ],
        variableType: [
            'string' as VariableType,
            {
                openNewVariableModal: (_, { variableType }) => variableType,
                openExistingVariableModal: (_, { variable }) => variable.type,
            },
        ],
        isModalOpen: [
            false as boolean,
            {
                openNewVariableModal: () => true,
                openExistingVariableModal: () => true,
                closeModal: () => false,
            },
        ],
        variable: [
            DEFAULT_VARIABLE as Variable,
            {
                openExistingVariableModal: (_, { variable }) => ({ ...variable }),
                openNewVariableModal: (_, { variableType }) => {
                    if (variableType === 'String') {
                        return {
                            id: '',
                            type: 'String',
                            name: '',
                            default_value: '',
                            code_name: '',
                        } as StringVariable
                    }

                    if (variableType === 'Number') {
                        return {
                            id: '',
                            type: 'Number',
                            name: '',
                            default_value: 0,
                            code_name: '',
                        } as NumberVariable
                    }

                    if (variableType === 'Boolean') {
                        return {
                            id: '',
                            type: 'Boolean',
                            name: '',
                            default_value: false,
                            code_name: '',
                        } as BooleanVariable
                    }

                    if (variableType === 'List') {
                        return {
                            id: '',
                            type: 'List',
                            name: '',
                            values: [],
                            default_value: '',
                            code_name: '',
                        } as ListVariable
                    }

                    throw new Error(`Unsupported variable type ${variableType}`)
                },
                updateVariable: (state, { variable }) => ({ ...state, ...variable } as Variable),
                closeModal: () => DEFAULT_VARIABLE,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        save: async () => {
            try {
                if (values.modalType === 'new') {
                    const variable = await api.insightVariables.create(values.variable)
                    actions.addVariable({ variableId: variable.id, code_name: variable.code_name })
                } else {
                    await api.insightVariables.update(values.variable.id, values.variable)
                }

                actions.getVariables()
                actions.closeModal()
            } catch (e: any) {
                const error = e as ApiError
                lemonToast.error(error.detail ?? error.message)
            }
        },
    })),
])

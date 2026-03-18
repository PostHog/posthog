import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { fetchInsightsUsingVariable } from 'scenes/data-management/variables/insightsLoader'
import { teamLogic } from 'scenes/teamLogic'

import { QueryBasedInsightModel } from '~/types'

import {
    BooleanVariable,
    DateVariable,
    ListVariable,
    NumberVariable,
    StringVariable,
    Variable,
    VariableType,
} from '../../types'
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

const getDefaultVariableForType = (variableType: VariableType): Variable => {
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

    if (variableType === 'Date') {
        return {
            id: '',
            type: 'Date',
            name: '',
            default_value: dayjs().format('YYYY-MM-DD HH:mm:00'),
            code_name: '',
        } as DateVariable
    }

    throw new Error(`Unsupported variable type ${variableType}`)
}

export const variableModalLogic = kea<variableModalLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableLogic']),
    props({ key: '' } as AddVariableLogicProps),
    key((props) => props.key),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [
            variableDataLogic,
            ['getVariables'],
            variablesLogic,
            ['addVariable', 'updateInternalSelectedVariable'],
        ],
    })),
    actions({
        openNewVariableModal: (variableType: VariableType) => ({ variableType }),
        openExistingVariableModal: (variable: Variable) => ({ variable }),
        closeModal: true,
        updateVariable: (variable: Variable) => ({ variable }),
        save: true,
        changeTypeExistingVariable: (variableType: VariableType) => ({ variableType }),
        setInsightsUsingVariable: (insights: QueryBasedInsightModel[]) => ({ insights }),
        setInsightsLoading: (loading: boolean) => ({ loading }),
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
                    return getDefaultVariableForType(variableType)
                },
                updateVariable: (state, { variable }) =>
                    ({
                        ...state,
                        ...variable,
                    }) as Variable,
                closeModal: () => DEFAULT_VARIABLE,
                changeTypeExistingVariable: (state, { variableType }) => {
                    const defaultVariable = getDefaultVariableForType(variableType)
                    return {
                        ...defaultVariable,
                        id: state.id,
                        name: state.name,
                        code_name: state.code_name,
                    }
                },
            },
        ],
        insightsUsingVariable: [
            [] as QueryBasedInsightModel[],
            {
                setInsightsUsingVariable: (_, { insights }) => insights,
                closeModal: () => [],
            },
        ],
        insightsLoading: [
            false as boolean,
            {
                setInsightsLoading: (_, { loading }) => loading,
                openExistingVariableModal: () => true,
                closeModal: () => false,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        openExistingVariableModal: async ({ variable }) => {
            // Load insights that use this variable
            if (variable.id && values.currentTeamId) {
                actions.setInsightsLoading(true)
                try {
                    const matchingInsights = await fetchInsightsUsingVariable(values.currentTeamId, variable.id)
                    actions.setInsightsUsingVariable(matchingInsights)
                } catch {
                    // Error already handled by fetchInsightsUsingVariable
                } finally {
                    actions.setInsightsLoading(false)
                }
            }
        },
        save: async () => {
            try {
                if (values.modalType === 'new') {
                    const variable = await api.insightVariables.create(values.variable)
                    actions.addVariable({ variableId: variable.id, code_name: variable.code_name })
                } else {
                    const variable = await api.insightVariables.update(values.variable.id, values.variable)
                    if (values.variableType !== values.variable.type) {
                        actions.updateInternalSelectedVariable({
                            variableId: variable.id,
                            code_name: variable.code_name,
                        })
                    }
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

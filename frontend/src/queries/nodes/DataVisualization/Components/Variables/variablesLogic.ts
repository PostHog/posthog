import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { getVariablesFromQuery, haveVariablesOrFiltersChanged } from 'scenes/insights/utils/queryUtils'

import { DataVisualizationNode, HogQLVariable } from '~/queries/schema/schema-general'
import { DashboardType } from '~/types'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable, VariableType } from '../../types'
import { variableDataLogic } from './variableDataLogic'
import type { variablesLogicType } from './variablesLogicType'

export interface VariablesLogicProps {
    key: string
    /** Disable any changes to the query */
    readOnly: boolean
    /** Dashboard ID for the current dashboard if we're viewing one */
    dashboardId?: DashboardType['id']

    queryInput?: string
    sourceQuery?: DataVisualizationNode
    setQuery?: (query: DataVisualizationNode) => void
    onUpdate?: (query: DataVisualizationNode) => void
}

const convertValueToCorrectType = (value: string, type: VariableType): number | string | boolean => {
    if (type === 'Number') {
        return Number(value)
    }

    if (type === 'Boolean' && typeof value === 'string') {
        return value.toLowerCase() === 'true'
    }

    return value
}

export const variablesLogic = kea<variablesLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variablesLogic']),
    props({ key: '' } as VariablesLogicProps),
    key((props) => props.key),
    connect(() => ({
        actions: [dataVisualizationLogic, ['setQuery', 'loadData'], variableDataLogic, ['getVariables']],
        values: [dataVisualizationLogic, ['query'], variableDataLogic, ['variables', 'variablesLoading']],
    })),
    actions(({ values }) => ({
        addVariable: (variable: HogQLVariable) => ({ variable }),
        _addVariable: (variable: HogQLVariable) => ({ variable }),
        addVariables: (variables: HogQLVariable[]) => ({ variables }),
        removeVariable: (variableId: string) => ({ variableId }),
        _removeVariable: (variableId: string) => ({ variableId }),
        updateVariableValue: (variableId: string, value: any, isNull: boolean) => ({
            variableId,
            value,
            isNull,
            allVariables: values.variables,
        }),
        setEditorQuery: (query: string) => ({ query }),
        updateSourceQuery: true,
        resetVariables: true,
        updateInternalSelectedVariable: (variable: HogQLVariable) => ({ variable }),
    })),
    propsChanged(({ props, actions, values }, oldProps) => {
        if (oldProps.queryInput !== props.queryInput) {
            actions.setEditorQuery(props.queryInput ?? '')
        }

        if (props.sourceQuery) {
            const variables = Object.values(props.sourceQuery?.source.variables ?? {})

            if (variables.length) {
                variables.forEach((variable) => {
                    actions._addVariable(variable)
                })
            }

            values.internalSelectedVariables.forEach((variable) => {
                if (!variables.map((n) => n.variableId).includes(variable.variableId)) {
                    actions._removeVariable(variable.variableId)
                }
            })
        }
    }),
    reducers({
        internalSelectedVariables: [
            [] as HogQLVariable[],
            {
                addVariable: (state, { variable }) => {
                    if (state.find((n) => variable.variableId === n.variableId)) {
                        return state
                    }

                    return [...state, { ...variable }]
                },
                _addVariable: (state, { variable }) => {
                    if (state.find((n) => variable.variableId === n.variableId)) {
                        return state
                    }

                    return [...state, { ...variable }]
                },
                addVariables: (_state, { variables }) => {
                    return variables.map((n) => ({ ...n }))
                },
                updateVariableValue: (state, { variableId, value, isNull, allVariables }) => {
                    const variableIndex = state.findIndex((n) => n.variableId === variableId)
                    if (variableIndex < 0) {
                        return state
                    }

                    const variableType = allVariables.find((n) => n.id === variableId)?.type
                    const valueWithType = convertValueToCorrectType(value, variableType ?? 'String')
                    const variablesInState = [...state]
                    variablesInState[variableIndex] = {
                        ...variablesInState[variableIndex],
                        value: valueWithType,
                        isNull,
                    }

                    return variablesInState
                },
                removeVariable: (state, { variableId }) => {
                    const stateCopy = [...state]
                    const index = stateCopy.findIndex((n) => n.variableId === variableId)
                    if (index >= 0) {
                        stateCopy.splice(index, 1)
                    }

                    return stateCopy
                },
                _removeVariable: (state, { variableId }) => {
                    const stateCopy = [...state]
                    const index = stateCopy.findIndex((n) => n.variableId === variableId)
                    if (index >= 0) {
                        stateCopy.splice(index, 1)
                    }

                    return stateCopy
                },
                resetVariables: () => {
                    return []
                },
                updateInternalSelectedVariable: (state, { variable }) => {
                    const variableIndex = state.findIndex((n) => n.variableId === variable.variableId)
                    if (variableIndex < 0) {
                        return state
                    }
                    const variablesInState = [...state]
                    variablesInState[variableIndex] = {
                        ...variable,
                    }

                    return variablesInState
                },
            },
        ],
        editorQuery: [
            '' as string,
            {
                setEditorQuery: (_, { query }) => query,
            },
        ],
    }),
    selectors({
        variablesForInsight: [
            (s) => [s.variables, s.internalSelectedVariables],
            (variables, internalSelectedVariables): Variable[] => {
                if (!variables.length || !internalSelectedVariables.length) {
                    return []
                }

                return internalSelectedVariables
                    .map(({ variableId, value, isNull }) => {
                        const v = variables.find((n) => n.id === variableId)
                        if (v) {
                            return { ...v, value, isNull } as Variable
                        }

                        return undefined
                    })
                    .filter((n): n is Variable => Boolean(n))
            },
        ],
        showVariablesBar: [
            () => [(_, props) => props.dashboardId],
            (dashboardId) => {
                return !dashboardId
            },
        ],
    }),
    listeners(({ props, values, actions }) => ({
        addVariable: () => {
            // dashboard items handle source query separately
            if (!props.readOnly) {
                actions.updateSourceQuery()
            }
        },
        removeVariable: () => {
            actions.updateSourceQuery()
        },
        updateVariableValue: () => {
            actions.updateSourceQuery()
        },
        updateSourceQuery: () => {
            if (!props.sourceQuery?.source) {
                return
            }

            const variables = values.internalSelectedVariables

            const query: DataVisualizationNode = {
                ...props.sourceQuery,
                source: {
                    ...props.sourceQuery?.source,
                    variables: variables.reduce(
                        (acc, cur) => {
                            if (cur.variableId) {
                                acc[cur.variableId] = {
                                    variableId: cur.variableId,
                                    value: cur.value,
                                    code_name: cur.code_name,
                                    isNull: cur.isNull,
                                }
                            }

                            return acc
                        },
                        {} as Record<string, HogQLVariable>
                    ),
                },
            }
            const queryVarsHaveChanged = haveVariablesOrFiltersChanged(query.source, props.sourceQuery?.source)

            if (!queryVarsHaveChanged) {
                return
            }

            props.setQuery?.(query)

            if (props.readOnly) {
                // Refresh the data manaully via dataNodeLogic when in insight view mode
                // actions.loadData(true, undefined, query.source)
                props.onUpdate?.(query)
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        editorQuery: (query: string) => {
            const queryVariableMatches = getVariablesFromQuery(query)

            if (!queryVariableMatches.length) {
                return
            }

            queryVariableMatches?.forEach((match) => {
                if (match === null) {
                    return
                }

                const variableExists = values.variables.find((n) => n.code_name === match)
                if (!variableExists) {
                    return
                }

                const variableAlreadySelected = values.internalSelectedVariables.find((n) => n.code_name === match)
                if (!variableAlreadySelected) {
                    actions.addVariable({ variableId: variableExists.id, code_name: variableExists.code_name })
                }
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.getVariables()
    }),
])

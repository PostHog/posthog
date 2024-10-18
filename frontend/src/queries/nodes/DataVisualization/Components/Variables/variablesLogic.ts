import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getVariablesFromQuery, haveVariablesOrFiltersChanged } from 'scenes/insights/utils/queryUtils'

import { DataVisualizationNode, HogQLVariable } from '~/queries/schema'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable, VariableType } from '../../types'
import { variableDataLogic } from './variableDataLogic'
import type { variablesLogicType } from './variablesLogicType'

export interface VariablesLogicProps {
    key: string
    /** Disable any changes to the query */
    readOnly: boolean
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
    connect({
        actions: [dataVisualizationLogic, ['setQuery', 'loadData'], variableDataLogic, ['getVariables']],
        values: [
            dataVisualizationLogic,
            ['query', 'insightLogicProps'],
            variableDataLogic,
            ['variables', 'variablesLoading'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    }),
    actions(({ values }) => ({
        addVariable: (variable: HogQLVariable) => ({ variable }),
        addVariables: (variables: HogQLVariable[]) => ({ variables }),
        removeVariable: (variableId: string) => ({ variableId }),
        updateVariableValue: (variableId: string, value: any) => ({
            variableId,
            value,
            allVariables: values.variables,
        }),
        setEditorQuery: (query: string) => ({ query }),
        updateSourceQuery: true,
    })),
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
                addVariables: (_state, { variables }) => {
                    return [...variables.map((n) => ({ ...n }))]
                },
                updateVariableValue: (state, { variableId, value, allVariables }) => {
                    const variableIndex = state.findIndex((n) => n.variableId === variableId)
                    if (variableIndex < 0) {
                        return state
                    }

                    const variableType = allVariables.find((n) => n.id === variableId)?.type
                    const valueWithType = convertValueToCorrectType(value, variableType ?? 'String')

                    const variablesInState = [...state]
                    variablesInState[variableIndex] = { ...variablesInState[variableIndex], value: valueWithType }

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
            },
        ],
        editorQuery: [
            '' as string,
            {
                setEditorQuery: (_, { query }) => query,
                setQuery: (_, { node }) => node.source.query,
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
                    .map(({ variableId, value }) => {
                        const v = variables.find((n) => n.id === variableId)
                        if (v) {
                            return { ...v, value } as Variable
                        }

                        return undefined
                    })
                    .filter((n): n is Variable => Boolean(n))
            },
        ],
        showVariablesBar: [
            (state) => [state.insightLogicProps],
            (insightLogicProps) => {
                return !insightLogicProps.dashboardId
            },
        ],
    }),
    listeners(({ props, values, actions }) => ({
        addVariable: () => {
            actions.updateSourceQuery()
        },
        removeVariable: () => {
            actions.updateSourceQuery()
        },
        updateVariableValue: () => {
            actions.updateSourceQuery()
        },
        updateSourceQuery: () => {
            if (!values.featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
                return
            }

            const variables = values.internalSelectedVariables

            const query: DataVisualizationNode = {
                ...values.query,
                source: {
                    ...values.query.source,
                    variables: variables.reduce((acc, cur) => {
                        if (cur.variableId) {
                            acc[cur.variableId] = {
                                variableId: cur.variableId,
                                value: cur.value,
                                code_name: cur.code_name,
                            }
                        }

                        return acc
                    }, {} as Record<string, HogQLVariable>),
                },
            }

            const queryVarsHaveChanged = haveVariablesOrFiltersChanged(query.source, values.query.source)
            if (!queryVarsHaveChanged) {
                return
            }

            actions.setQuery(query)

            if (props.readOnly) {
                // Refresh the data manaully via dataNodeLogic when in insight view mode
                actions.loadData(true, undefined, query.source)
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        editorQuery: (query: string) => {
            const queryVariableMatches = getVariablesFromQuery(query)

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
        query: (query: DataVisualizationNode) => {
            if (!values.featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
                return
            }

            const variables = Object.values(query.source.variables ?? {})

            if (variables.length) {
                actions.addVariables(variables)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
            return
        }

        actions.getVariables()
    }),
])

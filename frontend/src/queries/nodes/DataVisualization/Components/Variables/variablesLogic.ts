import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getVariablesFromQuery, haveVariablesOrFiltersChanged } from 'scenes/insights/utils/queryUtils'

import { DataVisualizationNode, HogQLVariable } from '~/queries/schema'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable } from '../../types'
import { variableDataLogic } from './variableDataLogic'
import type { variablesLogicType } from './variablesLogicType'

export interface VariablesLogicProps {
    key: string
    /** Disable any changes to the query */
    readOnly: boolean
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
    actions({
        addVariable: (variable: HogQLVariable) => ({ variable }),
        addVariables: (variables: HogQLVariable[]) => ({ variables }),
        removeVariable: (variableId: string) => ({ variableId }),
        updateVariableValue: (variableId: string, value: any) => ({ variableId, value }),
        setEditorQuery: (query: string) => ({ query }),
        resetVariables: true,
        updateSourceQuery: true,
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
                addVariables: (state, { variables }) => {
                    return [...state, ...variables.map((n) => ({ ...n }))]
                },
                updateVariableValue: (state, { variableId, value }) => {
                    const variableIndex = state.findIndex((n) => n.variableId === variableId)
                    if (variableIndex < 0) {
                        return state
                    }

                    const variablesInState = [...state]
                    variablesInState[variableIndex] = { ...variablesInState[variableIndex], value }

                    return variablesInState
                },
                removeVariable: (state, { variableId }) => {
                    const stateCopy = [...state]
                    const index = stateCopy.findIndex((n) => n.variableId === variableId)
                    if (index >= 0) {
                        stateCopy.splice(index)
                    }

                    return stateCopy
                },
                resetVariables: () => [],
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
            (s) => [s.variables, s.internalSelectedVariables, s.variablesLoading],
            (variables, internalSelectedVariables, variablesLoading): Variable[] => {
                if (!variables.length || !internalSelectedVariables.length || variablesLoading) {
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

            const variables = values.variablesForInsight

            const query: DataVisualizationNode = {
                ...values.query,
                source: {
                    ...values.query.source,
                    variables: variables.reduce((acc, cur) => {
                        if (cur.id) {
                            acc[cur.id] = {
                                variableId: cur.id,
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

            if (props.readOnly) {
                // Refresh the data manaully via dataNodeLogic when in insight view mode
                actions.loadData(true, undefined, query.source)
            } else {
                // Update the query source when in edit mode
                actions.setQuery(query)
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

                const variableAlreadySelected = values.variablesForInsight.find((n) => n.code_name === match)
                if (!variableAlreadySelected) {
                    actions.addVariable({ variableId: variableExists.id, code_name: variableExists.code_name })
                }
            })
        },
        query: (query: DataVisualizationNode) => {
            if (!values.featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
                return
            }

            actions.resetVariables()

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

import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getVariablesFromQuery } from 'scenes/insights/utils/queryUtils'

import { DataVisualizationNode, HogQLVariable } from '~/queries/schema'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable } from '../../types'
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
        actions: [dataVisualizationLogic, ['setQuery', 'loadData']],
        values: [dataVisualizationLogic, ['query'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        addVariable: (variable: HogQLVariable) => ({ variable }),
        updateVariableValue: (variableId: string, value: any) => ({ variableId, value }),
        setEditorQuery: (query: string) => ({ query }),
    }),
    reducers({
        internalSelectedVariables: [
            [] as HogQLVariable[],
            {
                addVariable: (state, { variable }) => {
                    return [...state, { ...variable }]
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
    loaders({
        variables: [
            [] as Variable[],
            {
                getVariables: async () => {
                    const insights = await api.insightVariables.list()

                    return insights.results
                },
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
    }),
    subscriptions(({ props, actions, values }) => ({
        variablesForInsight: (variables: Variable[]) => {
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

            if (!values.featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
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
    })),
    afterMount(({ actions, values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
            return
        }

        Object.values(values.query.source.variables ?? {}).forEach((variable) => {
            actions.addVariable(variable)
        })

        actions.getVariables()
    }),
])

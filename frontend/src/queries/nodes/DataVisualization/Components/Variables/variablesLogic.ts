import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'

import { HogQLVariable } from '~/queries/schema'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable } from '../../types'
import type { variablesLogicType } from './variablesLogicType'

export interface VariablesLogicProps {
    key: string
}

export const variablesLogic = kea<variablesLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variablesLogic']),
    props({ key: '' } as VariablesLogicProps),
    key((props) => props.key),
    connect({
        actions: [dataVisualizationLogic, ['setQuery']],
        values: [dataVisualizationLogic, ['query']],
    }),
    actions({
        addVariable: (variableId: string) => ({ variableId }),
    }),
    reducers({
        internalSelectedVariables: [
            [] as string[],
            {
                addVariable: (state, { variableId }) => {
                    return [...state, variableId]
                },
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
                    .map((variableId) => variables.find((n) => n.id === variableId))
                    .filter((n): n is Variable => Boolean(n))
            },
        ],
    }),
    subscriptions(({ actions, values }) => ({
        variablesForInsight: (variables: Variable[]) => {
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.query.source,
                    variables: variables.reduce((acc, cur) => {
                        if (cur.id) {
                            acc[cur.id] = {
                                variableId: cur.id,
                            }
                        }

                        return acc
                    }, {} as Record<string, HogQLVariable>),
                },
            })
        },
    })),
    afterMount(({ actions, values }) => {
        Object.keys(values.query.source.variables ?? {}).forEach((variableId) => {
            actions.addVariable(variableId)
        })

        actions.getVariables()
    }),
])

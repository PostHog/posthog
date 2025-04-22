import { lemonToast } from '@posthog/lemon-ui'
import { events, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { Variable } from '../../types'
import type { variableDataLogicType } from './variableDataLogicType'

export const variableDataLogic = kea<variableDataLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableDataLogic']),
    loaders(({ values }) => ({
        variables: [
            [] as Variable[],
            {
                getVariables: async () => {
                    const insights = await api.insightVariables.list()
                    return insights.results
                },
                deleteVariable: async (variableId: string) => {
                    try {
                        await api.insightVariables.delete(variableId)
                        lemonToast.success('Variable deleted successfully')
                    } catch (error) {
                        lemonToast.error('Failed to delete variable')
                    }
                    return [...values.variables.filter((variable) => variable.id !== variableId)]
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.getVariables()
        },
    })),
])

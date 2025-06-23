import { lemonToast } from '@posthog/lemon-ui'
import { kea, path } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import api from 'lib/api'

import { Variable } from '../../types'
import type { variableDataLogicType } from './variableDataLogicType'

export const variableDataLogic = kea<variableDataLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableDataLogic']),
    lazyLoaders(({ values }) => ({
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
                    } catch {
                        lemonToast.error('Failed to delete variable')
                    }
                    return values.variables.filter((variable) => variable.id !== variableId)
                },
            },
        ],
    })),
])

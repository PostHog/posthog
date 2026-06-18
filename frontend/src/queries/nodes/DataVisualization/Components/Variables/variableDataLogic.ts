import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { isSharedView } from '~/exporter/exporterViewLogic'

import { Variable } from '../../types'
import type { variableDataLogicType } from './variableDataLogicType'

export const variableDataLogic = kea<variableDataLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableDataLogic']),
    loaders(({ values }) => ({
        variables: [
            [] as Variable[],
            {
                loadVariables: async () => {
                    if (isSharedView()) {
                        return []
                    }
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
    afterMount(({ actions }) => {
        actions.loadVariables()
    }),
])

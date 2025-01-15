import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { Variable } from '../../types'
import type { variableDataLogicType } from './variableDataLogicType'

export const variableDataLogic = kea<variableDataLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Variables', 'variableDataLogic']),
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
])

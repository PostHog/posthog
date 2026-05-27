import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { autoresearchLogicType } from './autoresearchLogicType'
import { autoresearchList } from './generated/api'
import { AutoresearchPipelineApi } from './generated/api.schemas'

export const autoresearchLogic = kea<autoresearchLogicType>([
    path(['products', 'autoresearch', 'autoresearchLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    loaders(({ values }) => ({
        pipelines: [
            [] as AutoresearchPipelineApi[],
            {
                loadPipelines: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await autoresearchList(String(values.currentTeamId))
                    return response.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPipelines()
    }),
])

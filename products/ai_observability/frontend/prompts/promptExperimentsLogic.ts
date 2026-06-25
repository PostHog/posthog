import { actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { ApiConfig } from '~/lib/api'

import { experimentsList } from '../../../experiments/frontend/generated/api'
import type { ExperimentBasicApi } from '../../../experiments/frontend/generated/api.schemas'
import { createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'
import type { promptExperimentsLogicType } from './promptExperimentsLogicType'

export interface PromptExperimentsLogicProps {
    promptName: string
}

export const promptExperimentsLogic = kea<promptExperimentsLogicType>([
    path((key) => ['products', 'ai_observability', 'frontend', 'prompts', 'promptExperimentsLogic', key]),
    props({} as PromptExperimentsLogicProps),
    key((props) => props.promptName),

    connect(() => ({
        actions: [createPromptExperimentModalLogic, ['submitCreateSuccess']],
    })),

    actions({
        refresh: true,
    }),

    loaders(({ props }) => ({
        experiments: [
            [] as ExperimentBasicApi[],
            {
                loadExperiments: async () => {
                    const response = await experimentsList(String(ApiConfig.getCurrentTeamId()), {
                        prompt_name: props.promptName,
                        order: '-created_at',
                    })
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        refresh: () => actions.loadExperiments(),
        submitCreateSuccess: () => actions.loadExperiments(),
    })),

    afterMount(({ actions, props }) => {
        actions.loadExperiments()
        posthog.capture('llma prompt experiment tab viewed', { prompt_name: props.promptName })
    }),
])

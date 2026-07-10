import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { EvaluationRun } from './evaluations/types'
import type { generationEvaluationRunsLogicType } from './generationEvaluationRunsLogicType'
import { queryEvaluationRuns } from './utils'

export interface GenerationEvaluationRunsLogicProps {
    traceId: string
}

export const generationEvaluationRunsLogic = kea<generationEvaluationRunsLogicType>([
    path(['products', 'ai_observability', 'frontend', 'generationEvaluationRunsLogic']),
    props({} as GenerationEvaluationRunsLogicProps),
    key((props) => `trace-${props.traceId}`),

    actions({
        refreshGenerationEvaluationRuns: true,
        setSelectedEvaluationId: (evaluationId: string | null) => ({ evaluationId }),
    }),

    loaders(({ props, values }) => ({
        generationEvaluationRuns: [
            [] as EvaluationRun[],
            {
                loadGenerationEvaluationRuns: async () => {
                    try {
                        return await queryEvaluationRuns({
                            traceId: props.traceId,
                            forceRefresh: values.isForceRefresh,
                        })
                    } catch (error) {
                        console.error('Failed to load generation evaluation runs:', error)
                        return []
                    }
                },
            },
        ],
    })),

    reducers({
        isForceRefresh: [
            false,
            {
                refreshGenerationEvaluationRuns: () => true,
                loadGenerationEvaluationRunsSuccess: () => false,
                loadGenerationEvaluationRunsFailure: () => false,
            },
        ],
        selectedEvaluationId: [
            null as string | null,
            {
                setSelectedEvaluationId: (_, { evaluationId }) => evaluationId,
            },
        ],
    }),

    listeners(({ actions }) => ({
        refreshGenerationEvaluationRuns: () => {
            actions.loadGenerationEvaluationRuns()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadGenerationEvaluationRuns()
    }),
])

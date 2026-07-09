import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { EvaluationRun } from './evaluations/types'
import type { generationEvaluationRunsLogicType } from './generationEvaluationRunsLogicType'
import { queryEvaluationRuns } from './utils'

export interface GenerationEvaluationRunsByGenerationProps {
    lookupBy: 'generation'
    generationEventId: string
}

export interface GenerationEvaluationRunsByTraceProps {
    lookupBy: 'trace'
    traceId: string
}

export type GenerationEvaluationRunsLogicProps =
    | GenerationEvaluationRunsByGenerationProps
    | GenerationEvaluationRunsByTraceProps

export const generationEvaluationRunsLogic = kea<generationEvaluationRunsLogicType>([
    path(['products', 'ai_observability', 'frontend', 'generationEvaluationRunsLogic']),
    props({} as GenerationEvaluationRunsLogicProps),
    key((props) => (props.lookupBy === 'trace' ? `trace-${props.traceId}` : props.generationEventId)),

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
                            ...(props.lookupBy === 'trace'
                                ? { traceId: props.traceId }
                                : { generationEventId: props.generationEventId }),
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

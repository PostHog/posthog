import { afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { getCurrentTeamId } from '~/lib/utils/getAppContext'

import { evaluationsList } from './generated/api'
import type { EvaluationApi } from './generated/api.schemas'
import type { sentimentEvaluationAvailabilityLogicType } from './sentimentEvaluationAvailabilityLogicType'

export const sentimentEvaluationAvailabilityLogic = kea<sentimentEvaluationAvailabilityLogicType>([
    path(['products', 'ai_observability', 'frontend', 'sentimentEvaluationAvailabilityLogic']),

    loaders({
        sentimentEvaluations: [
            [] as EvaluationApi[],
            {
                loadSentimentEvaluations: async () => {
                    const response = await evaluationsList(String(getCurrentTeamId()), {
                        evaluation_type: 'sentiment',
                        limit: 1,
                    })
                    return response.results || []
                },
            },
        ],
    }),

    reducers({
        hasLoadedSentimentEvaluations: [
            false as boolean,
            {
                loadSentimentEvaluationsSuccess: () => true,
                loadSentimentEvaluationsFailure: () => true,
            },
        ],
    }),

    selectors({
        hasSentimentEvaluations: [
            (s) => [s.sentimentEvaluations],
            (sentimentEvaluations: EvaluationApi[]): boolean => sentimentEvaluations.length > 0,
        ],
    }),

    afterMount(({ actions, values }) => {
        if (!values.hasLoadedSentimentEvaluations && !values.sentimentEvaluationsLoading) {
            actions.loadSentimentEvaluations()
        }
    }),
])

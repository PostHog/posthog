import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { surveyDataProcessingLogicType } from './suveyDataProcessingLogicType'

export const surveyDataProcessingLogic = kea<surveyDataProcessingLogicType>([
    path(['scenes', 'surveys', 'suveyDataProcessingLogic']),
    actions({
        acceptSurveyDataProcessing: true,
        refuseSurveyDataProcessing: true,
    }),
    reducers({
        surveyDataProcessingAccepted: [
            false,
            { persist: true },
            {
                acceptSurveyDataProcessing: () => true,
                refuseSurveyDataProcessing: () => false,
            },
        ],
        surveyDataProcessingRefused: [
            false,
            { persist: true },
            {
                acceptSurveyDataProcessing: () => false,
                refuseSurveyDataProcessing: () => true,
            },
        ],
    }),
    listeners({
        acceptSurveyDataProcessing: () => {
            posthog.capture('survey_data_processing_accepted')
        },
        refuseSurveyDataProcessing: () => {
            posthog.capture('survey_data_processing_refused')
        },
    }),
])

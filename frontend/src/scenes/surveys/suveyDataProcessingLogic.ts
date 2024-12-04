import { actions, kea, path, reducers } from 'kea'

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
])

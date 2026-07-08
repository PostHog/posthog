import { kea, path, reducers } from 'kea'

import type { surveyQuestionLabelsLogicType } from './surveyQuestionLabelsLogicType'

// Toolbar shim — survey question labels come from an authenticated endpoint the toolbar can't
// reach on customer pages (lib/api is denied), so the labels are always empty here. Consumers
// (PropertyKeyInfo, taxonomy helpers) fall back to their generic labels.
export interface SurveyQuestionLabel {
    surveyId: string
    surveyName: string
    questionText: string
    questionIndex: number
}

export const surveyQuestionLabelsLogic = kea<surveyQuestionLabelsLogicType>([
    path(['toolbar', 'shims', 'surveyQuestionLabelsLogic']),
    reducers({
        surveyQuestionLabels: [{} as Record<string, SurveyQuestionLabel>, {}],
    }),
])

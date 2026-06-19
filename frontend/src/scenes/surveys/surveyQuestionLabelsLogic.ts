import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { surveyQuestionLabelsLogicType } from './surveyQuestionLabelsLogicType'

export interface SurveyQuestionLabel {
    surveyId: string
    surveyName: string
    questionText: string
    questionIndex: number
}

export const surveyQuestionLabelsLogic = kea<surveyQuestionLabelsLogicType>([
    path(['scenes', 'surveys', 'surveyQuestionLabelsLogic']),
    loaders(({ values }) => ({
        surveyQuestionLabels: [
            {} as Record<string, SurveyQuestionLabel>,
            {
                loadSurveyQuestionLabels: async () => {
                    // The endpoint returns one entry per question with an ID, across all the team's surveys.
                    // The payload is intentionally slim (≈100 bytes per question) so this scales to thousands.
                    const response = await api.surveys.questionLabels()
                    const labels: Record<string, SurveyQuestionLabel> = { ...values.surveyQuestionLabels }
                    for (const entry of response.labels) {
                        labels[entry.question_id] = {
                            surveyId: entry.survey_id,
                            surveyName: entry.survey_name,
                            questionText: entry.question_text,
                            questionIndex: entry.question_index,
                        }
                    }
                    return labels
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadSurveyQuestionLabels()
    }),
])

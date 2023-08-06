import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Breadcrumb, ProgressStatus, Survey } from '~/types'
import { urls } from 'scenes/urls'

import type { surveysLogicType } from './surveysLogicType'
import { lemonToast } from '@posthog/lemon-ui'

export function getSurveyStatus(survey: Survey): ProgressStatus {
    if (!survey.start_date) {
        return ProgressStatus.Draft
    } else if (!survey.end_date) {
        return ProgressStatus.Running
    }
    return ProgressStatus.Complete
}

export const surveysLogic = kea<surveysLogicType>([
    path(['scenes', 'surveys', 'surveysLogic']),
    loaders(({ values }) => ({
        surveys: {
            __default: [] as Survey[],
            loadSurveys: async () => {
                const response = await api.surveys.list()
                return response.results
            },
            deleteSurvey: async (id) => {
                await api.surveys.delete(id)
                return values.surveys.filter((survey) => survey.id !== id)
            },
            updateSurvey: async ({ id, updatePayload }) => {
                const updatedSurvey = await api.surveys.update(id, { ...updatePayload })
                return values.surveys.map((survey) => (survey.id === id ? updatedSurvey : survey))
            },
        },
    })),
    listeners(() => ({
        deleteSurveySuccess: () => {
            lemonToast.success('Survey deleted')
        },
        updateSurveySuccess: () => {
            lemonToast.success('Survey updated')
        },
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: 'Surveys',
                    path: urls.surveys(),
                },
            ],
        ],
        nonArchivedSurveys: [
            (s) => [s.surveys],
            (surveys: Survey[]): Survey[] => surveys.filter((survey) => !survey.archived),
        ],
        archivedSurveys: [
            (s) => [s.surveys],
            (surveys: Survey[]): Survey[] => surveys.filter((survey) => survey.archived),
        ],
    }),
    afterMount(async ({ actions }) => {
        await actions.loadSurveys()
    }),
])

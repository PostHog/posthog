import { afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Breadcrumb, ProgressStatus, Survey } from '~/types'
import { urls } from 'scenes/urls'

import type { surveysLogicType } from './surveysLogicType'
import { lemonToast } from '@posthog/lemon-ui'
import { router } from 'kea-router'

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
        },
    })),
    listeners(() => ({
        deleteSurveySuccess: () => {
            lemonToast.success('Survey deleted')
            router.actions.replace(urls.surveys())
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
    }),
    afterMount(async ({ actions }) => {
        await actions.loadSurveys()
    }),
])

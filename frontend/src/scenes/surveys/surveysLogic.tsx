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
                return response || { results: [] }
                // return response.results
                // {
                //     id: 1,
                //     name: 'Early access beta feature survey',
                //     responses: 33,
                //     type: 'Feature survey',
                //     created_by: 'Eric',
                //     created_at: 'Today',
                //     active: true,
                // },
                // {
                //     id: 2,
                //     name: 'PostHog 3000 beta survey',
                //     responses: 85,
                //     type: 'Feature survey',
                //     created_by: 'Michael',
                //     created_at: 'Yesterday',
                //     active: false,
                // },
                // {
                //     id: 3,
                //     name: 'General app survey',
                //     responses: 130,
                //     type: 'Button',
                //     created_by: 'Annika',
                //     created_at: '10 days ago',
                //     active: true,
                // },
            },
            deleteSurvey: async ({ id }) => {
                await api.surveys.delete(id)
                return values.surveys.filter((survey) => survey.id !== id)
            },
        },
    })),
    listeners(() => ({
        deleteSurveySuccess: () => {
            lemonToast.success('Survey deleted')
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

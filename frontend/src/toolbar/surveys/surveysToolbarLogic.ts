import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { Survey } from '~/types'

import type { surveysToolbarLogicType } from './surveysToolbarLogicType'

export type SurveyStatus = 'draft' | 'active' | 'complete'

export function getSurveyStatus(survey: Survey): SurveyStatus {
    if (!survey.start_date) {
        return 'draft'
    }
    if (survey.end_date) {
        return 'complete'
    }
    return 'active'
}

export const surveysToolbarLogic = kea<surveysToolbarLogicType>([
    path(['toolbar', 'surveys', 'surveysToolbarLogic']),

    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        showButtonSurveys: true,
        hideButtonSurveys: true,
    }),

    loaders(({ values }) => ({
        allSurveys: [
            [] as Survey[],
            {
                loadSurveys: async () => {
                    const params = new URLSearchParams()
                    params.set('archived', 'false')
                    if (values.searchTerm) {
                        params.set('search', values.searchTerm)
                    }
                    const url = `/api/projects/@current/surveys/?${params}`
                    const response = await toolbarFetch(url)
                    if (!response.ok) {
                        return []
                    }
                    const data = await response.json()
                    return data.results ?? data
                },
            },
        ],
    })),

    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),

    listeners(({ actions }) => ({
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSurveys()
        },
    })),
])

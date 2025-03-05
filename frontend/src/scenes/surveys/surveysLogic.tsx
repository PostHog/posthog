import { lemonToast } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import { isURL } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { SURVEY_PAGE_SIZE } from 'scenes/surveys/constants'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { AvailableFeature, Breadcrumb, ProgressStatus, Survey, SurveyType } from '~/types'

import type { surveysLogicType } from './surveysLogicType'

export enum SurveysTabs {
    Active = 'active',
    Yours = 'yours',
    Archived = 'archived',
    Notifications = 'notifications',
    History = 'history',
    Settings = 'settings',
}

export function getSurveyStatus(survey: Pick<Survey, 'start_date' | 'end_date'>): ProgressStatus {
    if (!survey.start_date) {
        return ProgressStatus.Draft
    } else if (!survey.end_date) {
        return ProgressStatus.Running
    }
    return ProgressStatus.Complete
}

function hasNextPage(surveys: CountedPaginatedResponse<Survey>): boolean {
    return surveys.next !== null && surveys.next !== undefined
}

export interface SurveysFilters {
    status: string
    created_by: null | number
    archived: boolean
}

export const surveysLogic = kea<surveysLogicType>([
    path(['scenes', 'surveys', 'surveysLogic']),
    connect(() => ({
        values: [userLogic, ['hasAvailableFeature'], teamLogic, ['currentTeam', 'currentTeamLoading']],
        actions: [teamLogic, ['loadCurrentTeam']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSurveysFilters: (filters: Partial<SurveysFilters>, replace?: boolean) => ({ filters, replace }),
        setTab: (tab: SurveysTabs) => ({ tab }),
        loadNextPage: true,
        loadBackendSearchResults: true,
    }),
    loaders(({ values }) => ({
        surveys: {
            __default: { results: [], count: 0 } as CountedPaginatedResponse<Survey>,
            loadSurveys: async () => {
                return await api.surveys.list()
            },
            loadNextPage: async () => {
                if (!values.surveys.next || !isURL(values.surveys.next)) {
                    return values.surveys
                }

                const url = new URL(values.surveys.next)
                const limit = parseInt(url.searchParams.get('limit') || SURVEY_PAGE_SIZE.toString())
                const offset = parseInt(url.searchParams.get('offset') || values.surveys.results.length.toString())

                const response = await api.surveys.list({ limit, offset })

                // deduplicate results
                const existingIds = new Set(values.surveys.results.map((s) => s.id))
                const newResults = response.results.filter((s) => !existingIds.has(s.id))

                return {
                    ...response,
                    results: [...values.surveys.results, ...newResults],
                }
            },
            loadBackendSearchResults: async () => {
                if (!values.searchTerm || !hasNextPage(values.surveys)) {
                    return values.surveys
                }

                const response = await api.surveys.list({
                    search: values.searchTerm,
                })

                const existingIds = new Set(values.surveys.results.map((s) => s.id))
                const newResults = response.results.filter((s) => !existingIds.has(s.id))

                return {
                    ...values.surveys,
                    results: [...values.surveys.results, ...newResults],
                }
            },
            deleteSurvey: async (id) => {
                await api.surveys.delete(id)
                return {
                    ...values.surveys,
                    results: values.surveys.results.filter((survey) => survey.id !== id),
                }
            },
            updateSurvey: async ({ id, updatePayload }) => {
                const updatedSurvey = await api.surveys.update(id, { ...updatePayload })
                return {
                    ...values.surveys,
                    results: values.surveys.results.map((survey) => (survey.id === id ? updatedSurvey : survey)),
                }
            },
        },
        surveysResponsesCount: {
            __default: {} as { [key: string]: number },
            loadResponsesCount: async () => {
                const surveysResponsesCount = await api.surveys.getResponsesCount()
                return surveysResponsesCount
            },
        },
    })),
    reducers({
        tab: [
            SurveysTabs.Active as SurveysTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        filters: [
            {
                archived: false,
                status: 'any',
                created_by: null,
            } as Partial<SurveysFilters>,
            {
                setSurveysFilters: (state, { filters }) => {
                    return { ...state, ...filters }
                },
            },
        ],
        hasNextPage: [
            true as boolean,
            {
                loadSurveysSuccess: (_, { surveys }) => hasNextPage(surveys),
                loadNextPageSuccess: (_, { surveys }) => hasNextPage(surveys),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        deleteSurveySuccess: () => {
            lemonToast.success('Survey deleted')
            router.actions.push(urls.surveys())
        },
        updateSurveySuccess: () => {
            lemonToast.success('Survey updated')
            actions.loadCurrentTeam()
        },
        setSurveysFilters: () => {
            actions.loadSurveys()
            actions.loadResponsesCount()
        },
        loadSurveysSuccess: () => {
            actions.loadCurrentTeam()

            if (values.surveys.results.some((survey) => survey.start_date)) {
                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.LaunchSurvey)
            }
        },
        loadResponsesCountSuccess: () => {
            if (Object.values(values.surveysResponsesCount).some((count) => count > 0)) {
                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.CollectSurveyResponses)
            }
        },
        setTab: ({ tab }) => {
            actions.setSurveysFilters({ ...values.filters, archived: tab === SurveysTabs.Archived })
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            await breakpoint(300) // Debounce for 300ms
            if (searchTerm && values.surveys.count > SURVEY_PAGE_SIZE) {
                actions.loadBackendSearchResults()
            }
        },
    })),
    selectors({
        searchedSurveys: [
            (selectors) => [selectors.surveys, selectors.searchTerm, selectors.filters],
            (surveys, searchTerm, filters) => {
                let searchedSurveys = surveys.results

                if (!searchTerm && Object.keys(filters).length === 0) {
                    return searchedSurveys
                }

                if (searchTerm) {
                    searchedSurveys = new Fuse(searchedSurveys, {
                        keys: ['key', 'name'],
                        ignoreLocation: true,
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                const { status, created_by, archived } = filters
                if (status !== 'any') {
                    searchedSurveys = searchedSurveys.filter((survey: Survey) => getSurveyStatus(survey) === status)
                }
                if (created_by) {
                    searchedSurveys = searchedSurveys.filter((survey: Survey) => survey.created_by?.id === created_by)
                }

                if (archived) {
                    searchedSurveys = searchedSurveys.filter((survey: Survey) => survey.archived)
                } else {
                    searchedSurveys = searchedSurveys.filter((survey: Survey) => !survey.archived)
                }

                return searchedSurveys
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Surveys,
                    name: 'Surveys',
                    path: urls.surveys(),
                },
            ],
        ],
        surveysStylingAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.SURVEYS_STYLING),
        ],
        globalSurveyAppearanceConfigAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.SURVEYS_STYLING),
        ],
        surveysHTMLAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.SURVEYS_TEXT_HTML),
        ],
        surveysMultipleQuestionsAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.SURVEYS_MULTIPLE_QUESTIONS),
        ],
        surveysRecurringScheduleAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.SURVEYS_RECURRING),
        ],
        surveysEventsAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.SURVEYS_EVENTS),
        ],
        surveysActionsAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature: (feature: AvailableFeature, currentUsage?: number | undefined) => boolean) =>
                hasAvailableFeature(AvailableFeature.SURVEYS_ACTIONS),
        ],
        showSurveysDisabledBanner: [
            (s) => [s.currentTeam, s.currentTeamLoading, s.surveys],
            (currentTeam, currentTeamLoading, surveys) => {
                return (
                    !currentTeamLoading &&
                    currentTeam &&
                    !currentTeam.surveys_opt_in &&
                    surveys.results.some((s) => s.start_date && !s.end_date && s.type !== SurveyType.API)
                )
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setTab: () => {
            return [router.values.location.pathname, { ...router.values.searchParams, tab: values.tab }]
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.surveys()]: (_, { tab }) => {
            if (tab) {
                actions.setTab(tab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSurveys()
        actions.loadResponsesCount()
    }),
])

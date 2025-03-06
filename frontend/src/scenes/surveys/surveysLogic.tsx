import { lemonToast } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
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

function hasMorePages(results: any[], count: number): boolean {
    return results.length < count
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
        loadNextSearchPage: true,
    }),
    loaders(({ values }) => ({
        data: {
            __default: {
                surveys: [] as Survey[],
                surveysCount: 0,
                searchSurveys: [] as Survey[],
                searchSurveysCount: 0,
            },
            loadSurveys: async () => {
                const response = await api.surveys.list()
                return {
                    ...values.data,
                    surveys: response.results,
                    surveysCount: response.count,
                }
            },
            loadNextPage: async () => {
                const offset = values.data.surveys.length
                const response = await api.surveys.list({
                    limit: SURVEY_PAGE_SIZE,
                    offset,
                })

                return {
                    ...values.data,
                    surveys: [...values.data.surveys, ...response.results],
                    surveysCount: response.count,
                }
            },
            loadSearchResults: async () => {
                const trimmedSearchTerm = values.searchTerm?.trim() || ''
                if (trimmedSearchTerm === '') {
                    return {
                        ...values.data,
                        searchSurveys: [],
                        searchSurveysCount: 0,
                    }
                }

                // Only do backend search if we have more total items than the page size
                if (values.data.surveysCount <= SURVEY_PAGE_SIZE) {
                    return values.data
                }

                const response = await api.surveys.list({
                    limit: SURVEY_PAGE_SIZE,
                    search: trimmedSearchTerm,
                })

                return {
                    ...values.data,
                    searchSurveys: response?.results || [],
                    searchSurveysCount: response?.count || 0,
                }
            },
            loadNextSearchPage: async () => {
                const offset = values.data.searchSurveys.length
                const response = await api.surveys.list({
                    search: values.searchTerm,
                    limit: SURVEY_PAGE_SIZE,
                    offset,
                })

                return {
                    ...values.data,
                    searchSurveys: [...values.data.searchSurveys, ...response.results],
                    searchSurveysCount: response.count,
                }
            },
            deleteSurvey: async (id) => {
                await api.surveys.delete(id)
                return {
                    ...values.data,
                    surveys: values.data.surveys.filter((survey) => survey.id !== id),
                    searchSurveys: values.data.searchSurveys.filter((survey) => survey.id !== id),
                }
            },
            updateSurvey: async ({ id, updatePayload }) => {
                const updatedSurvey = await api.surveys.update(id, { ...updatePayload })
                return {
                    ...values.data,
                    surveys: values.data.surveys.map((survey) => (survey.id === id ? updatedSurvey : survey)),
                    searchSurveys: values.data.searchSurveys.map((survey) =>
                        survey.id === id ? updatedSurvey : survey
                    ),
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
                loadSurveysSuccess: (_, { data }) => hasMorePages(data.surveys, data.surveysCount),
                loadNextPageSuccess: (_, { data }) => hasMorePages(data.surveys, data.surveysCount),
            },
        ],
        hasNextSearchPage: [
            false as boolean,
            {
                loadSearchResultsSuccess: (_, { data }) => hasMorePages(data.searchSurveys, data.searchSurveysCount),
                loadNextSearchPageSuccess: (_, { data }) => hasMorePages(data.searchSurveys, data.searchSurveysCount),
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

            if (values.data.surveys.some((survey) => survey.start_date)) {
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
            if (searchTerm && values.data.surveysCount > SURVEY_PAGE_SIZE) {
                actions.loadSearchResults()
            }
        },
    })),
    selectors({
        searchedSurveys: [
            (selectors) => [selectors.data, selectors.searchTerm, selectors.filters],
            (data, searchTerm, filters) => {
                let searchedSurveys = data.surveys

                if (searchTerm) {
                    // Always do frontend search first for better UX
                    const fuseResults = new Fuse(searchedSurveys, {
                        keys: ['key', 'name'],
                        ignoreLocation: true,
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)

                    // If we have backend search results (triggered when total count > page size)
                    // merge them with frontend results, removing duplicates
                    if (data.searchSurveys.length > 0) {
                        const seenIds = new Set(fuseResults.map((s) => s.id))
                        const uniqueBackendResults = data.searchSurveys.filter((s) => !seenIds.has(s.id))
                        searchedSurveys = [...fuseResults, ...uniqueBackendResults]
                    } else {
                        searchedSurveys = fuseResults
                    }
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
            (s) => [s.currentTeam, s.currentTeamLoading, s.data],
            (currentTeam, currentTeamLoading, data) => {
                return (
                    !currentTeamLoading &&
                    currentTeam &&
                    !currentTeam.surveys_opt_in &&
                    data.surveys.some((s: Survey) => s.start_date && !s.end_date && s.type !== SurveyType.API)
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

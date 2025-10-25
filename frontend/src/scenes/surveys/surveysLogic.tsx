import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { featureFlagLogic as enabledFlagLogic } from 'lib/logic/featureFlagLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { SURVEY_CREATED_SOURCE, SURVEY_PAGE_SIZE, SurveyTemplate } from 'scenes/surveys/constants'
import { sanitizeSurvey } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ActivationTask, activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { ActivityScope, AvailableFeature, Breadcrumb, ProductKey, ProgressStatus, Survey } from '~/types'

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

function hasMorePages(surveys: any[], count: number): boolean {
    return surveys.length < count
}

export interface SurveysFilters {
    status: string
    created_by: null | number
    archived: boolean
}

export interface SurveyDataState {
    surveys: Survey[]
    surveysCount: number
    searchSurveys: Survey[]
    searchSurveysCount: number
}

function mergeSurveysData(
    currentData: SurveyDataState,
    response: CountedPaginatedResponse<Survey>,
    appendResults = false
): SurveyDataState {
    if (response.results.length === 0) {
        return currentData
    }

    const surveys = appendResults ? [...currentData.surveys, ...response.results] : response.results

    return {
        ...currentData,
        surveys,
        surveysCount: response.count ?? currentData.surveysCount,
    }
}

function mergeSearchSurveysData(
    currentData: SurveyDataState,
    response: CountedPaginatedResponse<Survey>,
    appendResults = false
): SurveyDataState {
    if (response.results.length === 0) {
        return currentData
    }

    const searchSurveys =
        appendResults && response.results ? [...currentData.searchSurveys, ...response.results] : response.results

    return {
        ...currentData,
        searchSurveys,
        searchSurveysCount: response.count ?? 0,
    }
}

function deleteSurvey(surveys: Survey[], id: string): Survey[] {
    return surveys.filter((s) => s.id !== id)
}

function updateSurvey(surveys: Survey[], id: string, updatedSurvey: Survey): Survey[] {
    return surveys.map((s) => (s.id === id ? updatedSurvey : s))
}

export const surveysLogic = kea<surveysLogicType>([
    path(['scenes', 'surveys', 'surveysLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['hasAvailableFeature'],
            teamLogic,
            ['currentTeam', 'currentTeamLoading'],
            enabledFlagLogic,
            ['featureFlags as enabledFlags'],
        ],
        actions: [teamLogic, ['loadCurrentTeam', 'addProductIntent']],
    })),
    actions({
        setIsAppearanceModalOpen: (isOpen: boolean) => ({ isOpen }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSurveysFilters: (filters: Partial<SurveysFilters>, replace?: boolean) => ({ filters, replace }),
        setTab: (tab: SurveysTabs) => ({ tab }),
        loadNextPage: true,
        loadNextSearchPage: true,
    }),
    loaders(({ values, actions }) => ({
        data: {
            __default: {
                surveys: [] as Survey[],
                surveysCount: 0,
                searchSurveys: [] as Survey[],
                searchSurveysCount: 0,
            } as SurveyDataState,
            loadSurveys: async () => {
                const response = await api.surveys.list()
                return mergeSurveysData(values.data, response)
            },
            loadNextPage: async () => {
                const offset = values.data.surveys.length
                const response = await api.surveys.list({
                    limit: SURVEY_PAGE_SIZE,
                    offset,
                })

                return mergeSurveysData(values.data, response, true)
            },
            loadSearchResults: async () => {
                const trimmedSearchTerm = values.searchTerm?.trim() || ''
                if (trimmedSearchTerm === '') {
                    return mergeSearchSurveysData(values.data, { results: [], count: 0 })
                }

                // Only do backend search if we have more total items than the page size
                if (values.data.surveysCount <= SURVEY_PAGE_SIZE) {
                    return values.data
                }

                const response = await api.surveys.list({
                    limit: SURVEY_PAGE_SIZE,
                    search: trimmedSearchTerm,
                })

                return mergeSearchSurveysData(values.data, response)
            },
            loadNextSearchPage: async () => {
                const offset = values.data.searchSurveys.length
                const response = await api.surveys.list({
                    search: values.searchTerm,
                    limit: SURVEY_PAGE_SIZE,
                    offset,
                })

                return mergeSearchSurveysData(values.data, response, true)
            },
            deleteSurvey: async (id) => {
                const surveyId = String(id)
                await api.surveys.delete(surveyId)
                deleteFromTree('survey', surveyId)
                return {
                    ...values.data,
                    surveys: deleteSurvey(values.data.surveys, id),
                    searchSurveys: deleteSurvey(values.data.searchSurveys, id),
                }
            },
            updateSurvey: async ({
                id,
                updatePayload,
                intentContext,
            }: {
                id: string
                updatePayload: any
                intentContext?: ProductIntentContext
            }) => {
                const updatedSurvey = await api.surveys.update(id, { ...updatePayload })
                if (intentContext) {
                    actions.addProductIntent({
                        product_type: ProductKey.SURVEYS,
                        intent_context: intentContext,
                        metadata: { survey_id: id },
                    })
                }
                return {
                    ...values.data,
                    surveys: updateSurvey(values.data.surveys, id, updatedSurvey),
                    searchSurveys: updateSurvey(values.data.searchSurveys, id, updatedSurvey),
                }
            },
            createSurveyFromTemplate: async (surveyTemplate: SurveyTemplate) => {
                const response = await api.surveys.create(
                    sanitizeSurvey({
                        ...surveyTemplate,
                        name: surveyTemplate.templateType,
                    })
                )

                actions.addProductIntent({
                    product_type: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.SURVEY_CREATED,
                    metadata: {
                        survey_id: response.id,
                        source: SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE,
                        template_type: surveyTemplate.templateType,
                    },
                })

                // Navigate to the created survey
                router.actions.push(urls.survey(response.id))

                // Return updated data with the new survey
                return {
                    ...values.data,
                    surveys: [response, ...values.data.surveys],
                    surveysCount: values.data.surveysCount + 1,
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
        isAppearanceModalOpen: [
            false,
            {
                setIsAppearanceModalOpen: (_, { isOpen }) => isOpen,
            },
        ],
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
        deleteSurveySuccess: (_, __, action) => {
            lemonToast.success('Survey deleted')
            router.actions.push(urls.surveys())
            actions.addProductIntent({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_DELETED,
                metadata: {
                    survey_id: String(action.payload),
                },
            })
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

            actions.addProductIntent({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEYS_VIEWED,
                metadata: {
                    surveys_count: values.data.surveysCount,
                },
            })

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
                    name: sceneConfigurations[Scene.Surveys].name || 'Surveys',
                    path: urls.surveys(),
                    iconType: sceneConfigurations[Scene.Surveys].iconType || 'default_icon_type',
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
        showSurveysDisabledBanner: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                return !currentTeam?.surveys_opt_in
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.SURVEY,
            }),
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

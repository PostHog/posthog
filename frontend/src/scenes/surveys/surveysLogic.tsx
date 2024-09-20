import { lemonToast } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, Breadcrumb, ProgressStatus, Survey, SurveyType } from '~/types'

import type { surveysLogicType } from './surveysLogicType'

export enum SurveysTabs {
    Active = 'active',
    Yours = 'yours',
    Archived = 'archived',
    Notifications = 'notifications',
    History = 'history',
}

export function getSurveyStatus(survey: Survey): ProgressStatus {
    if (!survey.start_date) {
        return ProgressStatus.Draft
    } else if (!survey.end_date) {
        return ProgressStatus.Running
    }
    return ProgressStatus.Complete
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
    }),
    loaders(({ values }) => ({
        surveys: {
            __default: [] as Survey[],
            loadSurveys: async () => {
                const responseSurveys = await api.surveys.list()
                return responseSurveys.results
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
        },
        setTab: ({ tab }) => {
            actions.setSurveysFilters({ ...values.filters, archived: tab === SurveysTabs.Archived })
        },
    })),
    selectors({
        searchedSurveys: [
            (selectors) => [selectors.surveys, selectors.searchTerm, selectors.filters],
            (surveys, searchTerm, filters) => {
                let searchedSurveys = surveys

                if (!searchTerm && Object.keys(filters).length === 0) {
                    return searchedSurveys
                }

                if (searchTerm) {
                    searchedSurveys = new Fuse(searchedSurveys, {
                        keys: ['key', 'name'],
                        threshold: 0.3,
                    })
                        .search(searchTerm)
                        .map((result) => result.item)
                }

                const { status, created_by, archived } = filters
                if (status !== 'any') {
                    searchedSurveys = searchedSurveys.filter((survey) => getSurveyStatus(survey) === status)
                }
                if (created_by) {
                    searchedSurveys = searchedSurveys.filter((survey) => survey.created_by?.id === created_by)
                }

                if (archived) {
                    searchedSurveys = searchedSurveys.filter((survey) => survey.archived)
                } else {
                    searchedSurveys = searchedSurveys.filter((survey) => !survey.archived)
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
                    surveys.some((s) => s.start_date && !s.end_date && s.type !== SurveyType.API)
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

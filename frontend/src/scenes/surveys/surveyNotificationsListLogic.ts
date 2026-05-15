import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { CyclotronJobFiltersType, HogFunctionType, Survey, SurveyEventName, SurveyEventProperties } from '~/types'

import type { surveyNotificationsListLogicType } from './surveyNotificationsListLogicType'

const SURVEY_NOTIFICATION_LIST_LIMIT = 200
const SURVEY_INDEX_LIMIT = 1000

export function getSurveyIdsFromNotificationFilters(filters?: CyclotronJobFiltersType | null): string[] {
    const surveyIds = new Set<string>()

    for (const event of filters?.events ?? []) {
        for (const property of event.properties ?? []) {
            if (property.key !== SurveyEventProperties.SURVEY_ID) {
                continue
            }

            const value = property.value
            if (Array.isArray(value)) {
                value.forEach((surveyId) => {
                    if (typeof surveyId === 'string') {
                        surveyIds.add(surveyId)
                    }
                })
            } else if (typeof value === 'string') {
                surveyIds.add(value)
            }
        }
    }

    return Array.from(surveyIds)
}

export type KnownSurvey = Pick<Survey, 'id' | 'name' | 'archived' | 'created_at'>

export const surveyNotificationsListLogic = kea<surveyNotificationsListLogicType>([
    path(['scenes', 'surveys', 'surveyNotificationsListLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        toggleNotificationEnabled: (notificationId: string, enabled: boolean) => ({ notificationId, enabled }),
        deleteNotification: (notification: HogFunctionType) => ({ notification }),
        setSurveyPickerSearch: (search: string) => ({ search }),
        setSurveyPickerVisible: (visible: boolean) => ({ visible }),
    }),
    loaders(() => ({
        allNotifications: [
            [] as HogFunctionType[],
            {
                loadNotifications: async (): Promise<HogFunctionType[]> => {
                    const response = await api.hogFunctions.list({
                        filter_groups: [
                            {
                                events: [{ id: SurveyEventName.SENT, type: 'events' }],
                            },
                        ],
                        types: ['destination'],
                        limit: SURVEY_NOTIFICATION_LIST_LIMIT,
                        full: true,
                    })

                    return response.results.filter((notification) => !notification.deleted)
                },
            },
        ],
        knownSurveys: [
            [] as KnownSurvey[],
            {
                loadKnownSurveys: async (): Promise<KnownSurvey[]> => {
                    const response = await api.surveys.list({ limit: SURVEY_INDEX_LIMIT })
                    return response.results.map((survey) => ({
                        id: survey.id,
                        name: survey.name,
                        archived: survey.archived,
                        created_at: survey.created_at,
                    }))
                },
            },
        ],
    })),
    reducers({
        notificationsFailed: [
            false,
            {
                loadNotifications: () => false,
                loadNotificationsSuccess: () => false,
                loadNotificationsFailure: () => true,
            },
        ],
        knownSurveysFailed: [
            false,
            {
                loadKnownSurveys: () => false,
                loadKnownSurveysSuccess: () => false,
                loadKnownSurveysFailure: () => true,
            },
        ],
        surveyPickerSearch: [
            '',
            {
                setSurveyPickerSearch: (_, { search }) => search,
                setSurveyPickerVisible: (state, { visible }) => (visible ? state : ''),
            },
        ],
        surveyPickerVisible: [
            false,
            {
                setSurveyPickerVisible: (_, { visible }) => visible,
            },
        ],
    }),
    selectors({
        surveyCreatedAtById: [
            (s) => [s.knownSurveys],
            (knownSurveys: KnownSurvey[]) => new Map(knownSurveys.map((survey) => [survey.id, survey.created_at])),
        ],
        knownSurveyIds: [
            (s) => [s.knownSurveys],
            (knownSurveys: KnownSurvey[]) => new Set(knownSurveys.map((survey) => survey.id)),
        ],
        selectableSurveys: [
            (s) => [s.knownSurveys],
            (knownSurveys: KnownSurvey[]) =>
                knownSurveys
                    .filter((survey) => !survey.archived)
                    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')),
        ],
        filteredSelectableSurveys: [
            (s) => [s.selectableSurveys, s.surveyPickerSearch],
            (selectableSurveys: KnownSurvey[], surveyPickerSearch: string) => {
                const term = surveyPickerSearch.trim().toLowerCase()
                if (!term) {
                    return selectableSurveys
                }
                return selectableSurveys.filter((survey) => survey.name.toLowerCase().includes(term))
            },
        ],
        notifications: [
            (s) => [s.allNotifications, s.knownSurveyIds, s.surveyCreatedAtById, s.knownSurveysFailed],
            (
                allNotifications: HogFunctionType[],
                knownSurveyIds: Set<string>,
                surveyCreatedAtById: Map<string, string>,
                knownSurveysFailed: boolean
            ): HogFunctionType[] => {
                // If we couldn't load the survey index, skip the existence filter and show every
                // notification we did load. The filter is just orphan cleanup — a transient
                // surveys-API failure shouldn't hide live notifications from the user.
                const filtered = knownSurveysFailed
                    ? allNotifications
                    : allNotifications.filter((notification) => {
                          const linkedIds = getSurveyIdsFromNotificationFilters(notification.filters)
                          if (linkedIds.length === 0) {
                              return false
                          }
                          return linkedIds.some((surveyId) => knownSurveyIds.has(surveyId))
                      })

                const linkedSurveyCreatedAt = (notification: HogFunctionType): string => {
                    const surveyId = getSurveyIdsFromNotificationFilters(notification.filters)[0]
                    return (surveyId && surveyCreatedAtById.get(surveyId)) || ''
                }

                return filtered.slice().sort((a, b) => linkedSurveyCreatedAt(b).localeCompare(linkedSurveyCreatedAt(a)))
            },
        ],
        notificationsLoading: [
            (s) => [s.allNotificationsLoading, s.knownSurveysLoading],
            (allNotificationsLoading: boolean, knownSurveysLoading: boolean) =>
                allNotificationsLoading || knownSurveysLoading,
        ],
    }),
    listeners(({ actions, values }) => ({
        toggleNotificationEnabled: async ({ notificationId, enabled }) => {
            const target = values.allNotifications.find((notification) => notification.id === notificationId)
            if (!target) {
                return
            }
            const previousEnabled = target.enabled

            const applyEnabled = (next: boolean): void => {
                actions.loadNotificationsSuccess(
                    values.allNotifications.map((notification) =>
                        notification.id === notificationId ? { ...notification, enabled: next } : notification
                    )
                )
            }

            applyEnabled(enabled)

            try {
                await api.hogFunctions.update(notificationId, { enabled })
            } catch (error) {
                applyEnabled(previousEnabled)
                lemonToast.error('Failed to update notification')
                posthog.captureException(error, {
                    action: 'toggle-survey-notification-from-list',
                    notification: notificationId,
                })
            }
        },
        deleteNotification: async ({ notification }) => {
            const previous = values.allNotifications
            // Optimistically remove the row; restore on undo or on a swallowed API error.
            actions.loadNotificationsSuccess(previous.filter((n) => n.id !== notification.id))

            let callbackFired = false
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/hog_functions`,
                object: { id: notification.id, name: notification.name },
                callback: (undo) => {
                    callbackFired = true
                    if (undo) {
                        actions.loadNotifications()
                    }
                },
            })

            if (!callbackFired) {
                // deleteWithUndo swallows API errors and only fires the callback on success.
                actions.loadNotificationsSuccess(previous)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNotifications()
        actions.loadKnownSurveys()
    }),
])

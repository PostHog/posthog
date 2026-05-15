import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

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

export const surveyNotificationsListLogic = kea<surveyNotificationsListLogicType>([
    path(['scenes', 'surveys', 'surveyNotificationsListLogic']),
    actions({
        toggleNotificationEnabled: (notificationId: string, enabled: boolean) => ({ notificationId, enabled }),
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
            [] as Pick<Survey, 'id' | 'name' | 'archived'>[],
            {
                loadKnownSurveys: async (): Promise<Pick<Survey, 'id' | 'name' | 'archived'>[]> => {
                    const response = await api.surveys.list({ limit: SURVEY_INDEX_LIMIT })
                    return response.results.map((survey) => ({
                        id: survey.id,
                        name: survey.name,
                        archived: survey.archived,
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
    }),
    selectors({
        knownSurveyIds: [
            (s) => [s.knownSurveys],
            (knownSurveys: Pick<Survey, 'id' | 'name' | 'archived'>[]) =>
                new Set(knownSurveys.map((survey) => survey.id)),
        ],
        selectableSurveys: [
            (s) => [s.knownSurveys],
            (knownSurveys: Pick<Survey, 'id' | 'name' | 'archived'>[]) =>
                knownSurveys.filter((survey) => !survey.archived),
        ],
        notifications: [
            (s) => [s.allNotifications, s.knownSurveyIds, s.knownSurveysFailed],
            (
                allNotifications: HogFunctionType[],
                knownSurveyIds: Set<string>,
                knownSurveysFailed: boolean
            ): HogFunctionType[] => {
                // If we couldn't load the survey index, skip the existence filter and show every
                // notification we did load. The filter is just orphan cleanup — a transient
                // surveys-API failure shouldn't hide live notifications from the user.
                if (knownSurveysFailed) {
                    return allNotifications
                }
                return allNotifications.filter((notification) => {
                    const linkedIds = getSurveyIdsFromNotificationFilters(notification.filters)
                    if (linkedIds.length === 0) {
                        return false
                    }
                    return linkedIds.some((surveyId) => knownSurveyIds.has(surveyId))
                })
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
    })),
    afterMount(({ actions }) => {
        actions.loadNotifications()
        actions.loadKnownSurveys()
    }),
])

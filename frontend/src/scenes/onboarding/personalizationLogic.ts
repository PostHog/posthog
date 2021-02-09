import { kea } from 'kea'
import posthog from 'posthog-js'
import { personalizationLogicType } from './personalizationLogicType'
import { organizationLogic } from 'scenes/organizationLogic'
import { PersonalizationData } from '~/types'
import { router } from 'kea-router'

export const personalizationLogic = kea<personalizationLogicType<PersonalizationData>>({
    actions: {
        setPersonalizationData: (payload: PersonalizationData) => ({ payload }),
        appendPersonalizationData: (key: 'role' | 'products' | 'technical', value: string | string[] | null) => ({
            key,
            value,
        }),
        reportPersonalizationSkipped: true,
        reportPersonalization: (payload: PersonalizationData, step_completed_fully: boolean) => ({
            payload,
            step_completed_fully,
        }),
    },
    reducers: {
        personalizationData: [
            {} as PersonalizationData,
            {
                setPersonalizationData: (_, { payload }) => payload,
                appendPersonalizationData: (state, { key, value }) => ({ ...state, [key]: value }),
            },
        ],
    },
    listeners: {
        reportPersonalizationSkipped: async () => {
            posthog.capture('personalization skipped')
        },
        reportPersonalization: async ({ payload, step_completed_fully }) => {
            posthog.people.set_once(payload)
            posthog.capture('personalization finalized', {
                step_completed_fully,
                payload,
                number_of_answers: Object.keys(payload).length,
            })
            organizationLogic.actions.updateOrganization({ personalization: payload })
        },
        [organizationLogic.actionTypes.updateOrganizationSuccess]: async () => {
            window.location.href = '/'
        },
        [organizationLogic.actionTypes.loadCurrentOrganizationSuccess]: async () => {
            // Edge case in case this logic loaded before the api/organization request is completed
            const personalization = organizationLogic.values.currentOrganization?.personalization
            if (personalization && Object.keys(personalization).length) {
                router.actions.push('/setup')
            }
        },
    },
    events: {
        afterMount: () => {
            const personalization = organizationLogic.values.currentOrganization?.personalization
            if (personalization && Object.keys(personalization).length) {
                // If personalization has already been filled, this screen should no longer be loaded
                router.actions.push('/setup')
            }
        },
    },
})

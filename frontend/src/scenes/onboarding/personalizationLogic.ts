import { kea } from 'kea'
import posthog from 'posthog-js'
import { personalizationLogicType } from './personalizationLogicType'
import { organizationLogic } from 'scenes/organizationLogic'
import { PersonalizationData } from '~/types'

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
            posthog.capture('personalization completed', {
                step_completed_fully,
                payload,
                number_of_answers: Object.keys(payload).length,
            })
            organizationLogic.actions.updateOrganization({ personalization: payload })

            window.location.href = '/'
        },
    },
})

import { kea } from 'kea'
import posthog from 'posthog-js'
import { personalizationLogicType } from './personalizationLogicType'
import { organizationLogic } from 'scenes/organizationLogic'

export const personalizationLogic = kea<personalizationLogicType>({
    actions: {
        setPersonalizationData: (payload: Record<string, string | null>) => ({ payload }),
        appendPersonalizationData: (payload: Record<string, string | null>) => ({ payload }),
        reportPersonalizationSkipped: true,
        reportPersonalization: (payload: Record<string, string | null>, step_completed_fully: boolean) => ({
            payload,
            step_completed_fully,
        }),
    },
    reducers: {
        personalizationData: [
            {} as Record<string, string | null>,
            {
                setPersonalizationData: (_, { payload }) => payload,
                appendPersonalizationData: (state, { payload }) => {
                    return { ...state, ...payload }
                },
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

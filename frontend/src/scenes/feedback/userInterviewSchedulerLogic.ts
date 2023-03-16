import { actions, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagType } from '~/types'
import { userInterviewSchedulerLogicType } from './userInterviewSchedulerLogicType'

export const FLAG_PREFIX = 'interview-'

export type InterviewFlag = {
    key: string
    title: string
    body: string
    description: string
    bookingLink: string
}

export const userInterviewSchedulerLogic = kea<userInterviewSchedulerLogicType>([
    path(['scenes', 'feedback', 'userInterviewSchedulerLogic']),
    actions({
        toggleSchedulerInstructions: true,
        toggleInterviewFlagModal: true,
    }),
    reducers({
        schedulerInstructions: [
            false as boolean,
            {
                toggleSchedulerInstructions: (state) => !state,
            },
        ],
        interviewFlagModal: [
            true as boolean,
            {
                toggleInterviewFlagModal: (state) => !state,
            },
        ],
    }),
    forms(({ values }) => ({
        interviewFlag: {
            defaults: {
                key: 'interview-' as string,
                title: 'Help improve our product!' as string,
                body: 'We would love to hear your feedback on a short call' as string,
                description: 'Description' as string,
                bookingLink: 'https://calendly.com/...' as string,
            },
            errors: ({ key, title, body, bookingLink }: Record<string, string>) => ({
                key: !key
                    ? 'Please enter a key'
                    : !key.startsWith(FLAG_PREFIX)
                    ? `Key must start with "${FLAG_PREFIX}"`
                    : key.length < FLAG_PREFIX.length + 1
                    ? `Key must be more than just ${FLAG_PREFIX}`
                    : undefined,
                title: !title ? 'Please enter a title' : undefined,
                body: !body ? 'Please enter a body' : undefined,
                bookingLink: !bookingLink ? 'Please enter a booking link' : undefined,
            }),
            submit: async (formValues) => {
                console.log('submitting', formValues)
                // create the flag
                // then redirect to the created flag so you can manage rollout
                featureFlagLogic.mount()
                const flag: Partial<FeatureFlagType> = {
                    key: formValues.key,
                    name: formValues.title,
                    rollout_percentage: 0,
                    active: true,
                    filters: {
                        payloads: values.interviewFlagPayload,
                        groups: [],
                        multivariate: null,
                    },
                    deleted: false,
                }

                featureFlagLogic.actions.saveFeatureFlag(flag)
            },
        },
    })),
    selectors(({ selectors }) => ({
        interviewFlagPayload: [
            () => [selectors.interviewFlag],
            (interviewFlag: InterviewFlag) => {
                const { title, body, bookingLink } = interviewFlag
                return { title, body, bookingLink }
            },
        ],
    })),
])

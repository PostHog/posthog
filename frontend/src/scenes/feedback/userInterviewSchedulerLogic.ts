import { actions, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { isURL } from 'lib/utils'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { FeatureFlagGroupType, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import type { userInterviewSchedulerLogicType } from './userInterviewSchedulerLogicType'

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
            false as boolean,
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
                // check it's a valid url using regex
                bookingLink: !bookingLink
                    ? 'Please enter a booking link'
                    : !isURL(bookingLink)
                    ? 'Please enter a valid booking link'
                    : undefined,
            }),
            submit: async (formValues) => {
                const groups: FeatureFlagGroupType[] = [
                    {
                        variant: null,
                        properties: [
                            {
                                key: `Seen User Interview Invitation - ${formValues.key}`,
                                operator: PropertyOperator.IsNotSet,
                                type: PropertyFilterType.Person,
                                value: PropertyOperator.IsNotSet,
                            },
                        ],
                        rollout_percentage: 0,
                    },
                ]
                const flag: Partial<FeatureFlagType> = {
                    key: formValues.key,
                    tags: ['User Interview'],
                    name: formValues.description,
                    rollout_percentage: 0,
                    active: true,
                    filters: {
                        payloads: { true: JSON.stringify(values.interviewFlagPayload, null, 4) },
                        groups,
                        multivariate: null,
                    },
                    deleted: false,
                }

                featureFlagLogic.mount()
                featureFlagLogic.actions.saveFeatureFlag(flag)
            },
        },
    })),
    selectors(({ selectors }) => ({
        interviewFlagPayload: [
            () => [selectors.interviewFlag],
            (interviewFlag: InterviewFlag) => {
                const { title, body, bookingLink } = interviewFlag
                return { invitationTitle: title, invitationBody: body, bookingLink }
            },
        ],
    })),
])

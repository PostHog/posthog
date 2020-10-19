import { kea } from 'kea'
import api from '../lib/api'
import { posthogEvents } from 'lib/utils'
import { userLogicType } from 'types/scenes/userLogicType'
import { UserType, UserUpdateType } from '~/types'

interface EventProperty {
    value: string
    label: string
}

export const userLogic = kea<userLogicType<UserType, EventProperty, UserUpdateType>>({
    actions: () => ({
        loadUser: (resetOnFailure?: boolean) => ({ resetOnFailure }),
        setUser: (user: UserType | null, updateKey?: string) => ({
            user: user && ({ ...user } as UserType),
            updateKey,
        }), // make and use a copy of user to patch some legacy issues
        userUpdateRequest: (update: UserUpdateType, updateKey?: string) => ({ update, updateKey }),
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({ user, updateKey }),
        userUpdateFailure: (error: string, updateKey?: string) => ({ updateKey, error }),
        completedOnboarding: true,
        logout: true,
    }),

    reducers: {
        user: [
            null as UserType | null,
            {
                setUser: (_, payload) => payload.user,
                userUpdateSuccess: (_, payload) => payload.user,
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => actions.loadUser(true),
    }),

    selectors: ({ selectors }) => ({
        eventProperties: [
            () => [selectors.user],
            (user) =>
                user?.team.event_properties.map(
                    (property: string) => ({ value: property, label: property } as EventProperty)
                ) || ([] as EventProperty[]),
        ],
        eventPropertiesNumerical: [
            () => [selectors.user],
            (user) =>
                user?.team.event_properties_numerical.map(
                    (property: string) => ({ value: property, label: property } as EventProperty)
                ) || ([] as EventProperty[]),
        ],
        eventNames: [() => [selectors.user], (user) => user?.team.event_names || []],
        customEventNames: [
            () => [selectors.user],
            (user) => {
                return user?.team.event_names.filter((event: string) => !event.startsWith('!')) || []
            },
        ],
        eventNamesGrouped: [
            () => [selectors.user],
            (user) => {
                const data = [
                    { label: 'Custom events', options: [] as EventProperty[] },
                    { label: 'PostHog events', options: [] as EventProperty[] },
                ]
                user?.team.event_names.forEach((name: string) => {
                    const format = { label: name, value: name } as EventProperty
                    if (posthogEvents.includes(name)) return data[1].options.push(format)
                    data[0].options.push(format)
                })
                return data
            },
        ],
    }),

    listeners: ({ actions }) => ({
        loadUser: async ({ resetOnFailure }) => {
            try {
                const user = await api.get('api/user')
                actions.setUser(user)

                if (user && user.id) {
                    const Sentry = (window as any).Sentry
                    Sentry?.setUser({
                        email: user.email,
                        id: user.id,
                    })

                    const posthog = (window as any).posthog
                    if (posthog) {
                        if (posthog.get_distinct_id() !== user.distinct_id) {
                            posthog.reset()
                        }

                        posthog.identify(user.distinct_id, {
                            email: user.anonymize_data ? null : user.email,
                        })
                        posthog.register({
                            posthog_version: user.posthog_version,
                            has_slack_webhook: !!user.team?.slack_incoming_webhook,
                        })
                    }
                }
            } catch {
                if (resetOnFailure) {
                    actions.setUser(null)
                }
            }
        },
        userUpdateRequest: async ({ update, updateKey }) => {
            try {
                const user = await api.update('api/user', update)
                actions.userUpdateSuccess(user, updateKey)
            } catch (error) {
                actions.userUpdateFailure(error, updateKey)
            }
        },
        logout: () => {
            window.posthog?.reset()
            window.location.href = '/logout'
        },
    }),
})

import { kea } from 'kea'
import api from '../lib/api'
import { posthogEvents } from 'lib/utils'
import { userLogicType } from './userLogicType'
import { UserType } from '~/types'

export const userLogic = kea<userLogicType<UserType>>({
    actions: () => ({
        loadUser: true,
        setUser: (user: UserType | null, updateKey?: string) => ({ user: { ...user } as UserType, updateKey }), // make and use a copy of user to patch some legacy issues
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => ({ update, updateKey }),
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({ user, updateKey }),
        userUpdateFailure: (error: string, updateKey?: string) => ({ updateKey, error }),
    }),

    reducers: {
        user: [
            null as UserType | null,
            {
                setUser: (state, payload): UserType => payload.user,
                userUpdateSuccess: (state, payload): UserType => payload.user,
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: actions.loadUser,
    }),

    selectors: ({ selectors }) => ({
        eventProperties: [
            (s) => [s.user],
            (user) => user?.team.event_properties.map((property) => ({ value: property, label: property })) || [],
        ],
        eventNames: [() => [selectors.user], (user) => user?.team.event_names],
        customEventNames: [
            () => [selectors.user],
            (user) => {
                const eventNames = user?.team.event_names
                const regex = new RegExp('^[^$].*')
                const filtered = eventNames?.filter((event) => event.match(regex))
                return filtered || []
            },
        ],
        eventNamesGrouped: [
            () => [selectors.user],
            (user) => {
                const data = [
                    { label: 'Custom events', options: [] as { label: string; value: string }[] },
                    { label: 'PostHog events', options: [] as { label: string; value: string }[] },
                ]
                user?.team.event_names.forEach((name) => {
                    const format = { label: name, value: name }
                    if (posthogEvents.indexOf(name) > -1) {
                        return data[1].options.push(format)
                    }
                    data[0].options.push(format)
                })
                return data
            },
        ],
    }),

    listeners: ({ actions }) => ({
        loadUser: async () => {
            try {
                const user: UserType = await api.get('api/user')
                actions.setUser(user)

                const Sentry = (window as any).Sentry
                const PostHog = (window as any).posthog

                if (user && user.id) {
                    Sentry?.setUser({
                        email: user.email,
                        id: user.id,
                    })
                    if (PostHog) {
                        PostHog.identify(user.distinct_id)
                        PostHog.register({
                            posthog_version: user.posthog_version,
                            has_slack_webhook: !!user.team?.slack_incoming_webhook,
                        })
                    }
                }
            } catch (error) {
                actions.setUser(null)
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
    }),
})

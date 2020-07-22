import { kea } from 'kea'
import api from '../lib/api'
import { posthogEvents } from 'lib/utils'

export const userLogic = kea({
    actions: () => ({
        loadUser: true,
        setUser: (user, updateKey) => ({ user: { ...user }, updateKey }), // make and use a copy of user to patch some legacy issues
        userUpdateRequest: (update, updateKey) => ({ update, updateKey }),
        userUpdateSuccess: (user, updateKey) => ({ user, updateKey }),
        userUpdateFailure: (updateKey, error) => ({ updateKey, error }),
    }),

    reducers: ({ actions }) => ({
        user: [
            null,
            {
                [actions.setUser]: (_, payload) => payload.user,
                [actions.userUpdateSuccess]: (_, payload) => payload.user,
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadUser,
    }),

    selectors: ({ selectors }) => ({
        eventProperties: [
            () => [selectors.user],
            (user) => user.team.event_properties.map((property) => ({ value: property, label: property })),
        ],
        eventNames: [() => [selectors.user], (user) => user.team.event_names],
        customEventNames: [
            () => [selectors.user],
            (user) => {
                return user.team.event_names.filter((event) => !event.startsWith('!'))
            },
        ],
        eventNamesGrouped: [
            () => [selectors.user],
            (user) => {
                let data = [
                    { label: 'Custom events', options: [] },
                    { label: 'PostHog events', options: [] },
                ]
                user.team.event_names.forEach((name) => {
                    let format = { label: name, value: name }
                    if (posthogEvents.indexOf(name) > -1) return data[1].options.push(format)
                    data[0].options.push(format)
                })
                return data
            },
        ],
    }),

    listeners: ({ actions }) => ({
        [actions.loadUser]: async () => {
            try {
                const user = await api.get('api/user')
                actions.setUser(user)

                if (user && user.id) {
                    window.Sentry &&
                        window.Sentry.setUser({
                            email: user.email,
                            id: user.id,
                        })
                    if (window.posthog) {
                        window.posthog.identify(user.distinct_id)
                        window.posthog.register({
                            posthog_version: user.posthog_version,
                            has_slack_webhook: !!user.team?.slack_incoming_webhook,
                        })
                    }
                }
            } catch (error) {
                actions.setUser(null)
            }
        },
        [actions.userUpdateRequest]: async ({ update, updateKey }) => {
            try {
                const user = await api.update('api/user', update)
                actions.userUpdateSuccess(user, updateKey)
            } catch (error) {
                actions.userUpdateFailure(updateKey, error)
            }
        },
    }),
})

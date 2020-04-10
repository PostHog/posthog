import { kea } from 'kea'
import api from '../lib/api'

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

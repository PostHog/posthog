import React from 'react'
import { kea } from 'kea'
import api from '../lib/api'
import { posthogEvents } from 'lib/utils'
import { toast } from 'react-toastify'

export const userLogic = kea({
    actions: () => ({
        loadUser: true,
        setUser: (user, updateKey) => ({ user: { ...user }, updateKey }), // make and use a copy of user to patch some legacy issues
        createPersonalAPIKeyRequest: (label) => ({ label }),
        createPersonalAPIKeySuccess: (user, key) => ({ user, key }),
        createPersonalAPIKeyFailure: (label) => ({ label }),
        deletePersonalAPIKeyRequest: (key) => ({ key }),
        deletePersonalAPIKeySuccess: (user, key) => ({ user, key }),
        deletePersonalAPIKeyFailure: (key) => ({ key }),
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
                [actions.createPersonalAPIKeySuccess]: (_, payload) => {
                    const newUser = { ...payload.user }
                    newUser.personal_api_keys = [payload.key, ...payload.user.personal_api_keys]
                    return newUser
                },
                [actions.deletePersonalAPIKeySuccess]: (_, payload) => {
                    const newUser = { ...payload.user }
                    newUser.personal_api_keys = payload.user.personal_api_keys.filter(
                        (current_key) => current_key.id !== payload.key.id
                    )
                    return newUser
                },
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

    listeners: ({ actions, selectors }) => ({
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
        [actions.createPersonalAPIKeyRequest]: async ({ label }) => {
            let newKey
            try {
                newKey = await api.create('api/personal_api_key/', { label })
            } catch (e) {
                actions.createPersonalAPIKeyFailure(label)
                return
            }
            const user = selectors.user()
            actions.createPersonalAPIKeySuccess(user, newKey)
        },
        [actions.createPersonalAPIKeySuccess]: ({ key }) => {
            toast(<div className="text-success">Personal API key "{key.label}" successfully created</div>)
        },
        [actions.createPersonalAPIKeyFailure]: ({ label }) => {
            toast(<div className="text-danger">Could not create personal API key "{label}"</div>)
        },
        [actions.deletePersonalAPIKeyRequest]: async ({ key }) => {
            try {
                await api.delete(`api/personal_api_key/${key.id}/`)
            } catch (e) {
                actions.deletePersonalAPIKeyFailure(key)
                return
            }
            const user = selectors.user()
            actions.deletePersonalAPIKeySuccess(user, key)
        },
        [actions.deletePersonalAPIKeySuccess]: ({ key }) => {
            toast(<div className="text-success">Personal API key "{key.label}" successfully deleted</div>)
        },
        [actions.deletePersonalAPIKeyFailure]: ({ key }) => {
            toast(<div className="text-danger">Could not delete personal API key "{key.label}"</div>)
        },
    }),
})

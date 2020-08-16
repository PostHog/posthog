import { kea } from 'kea'
import React from 'react'
import { toast } from 'react-toastify'
import api from '../lib/api'
import { posthogEvents } from 'lib/utils'
import { userLogicType } from 'types/scenes/userLogicType'
import { UserType, PersonalAPIKeyType } from '~/types'

interface EventProperty {
    value: string
    label: string
}

export const userLogic = kea<userLogicType<UserType, EventProperty>>({
    actions: () => ({
        loadUser: true,
        setUser: (user: UserType | null, updateKey?: string) => ({
            user: user && ({ ...user } as UserType),
            updateKey,
        }), // make and use a copy of user to patch some legacy issues
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => ({ update, updateKey }),
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({ user, updateKey }),
        userUpdateFailure: (error: string, updateKey?: string) => ({ updateKey, error }),
        createPersonalAPIKeyRequest: (label: string) => ({ label }),
        createPersonalAPIKeySuccess: (user: UserType, key: PersonalAPIKeyType) => ({ user, key }),
        createPersonalAPIKeyFailure: (label: string) => ({ label }),
        deletePersonalAPIKeyRequest: (key: PersonalAPIKeyType) => ({ key }),
        deletePersonalAPIKeySuccess: (user: UserType, key: PersonalAPIKeyType) => ({ user, key }),
        deletePersonalAPIKeyFailure: (key: PersonalAPIKeyType) => ({ key }),
    }),

    reducers: {
        user: [
            null as UserType | null,
            {
                setUser: (_, payload) => payload.user,
                userUpdateSuccess: (_, payload) => payload.user,
                createPersonalAPIKeySuccess: (_, payload) => {
                    const newUser = { ...payload.user }
                    newUser.personal_api_keys = [payload.key, ...payload.user.personal_api_keys]
                    return newUser
                },
                deletePersonalAPIKeySuccess: (_, payload) => {
                    const newUser = { ...payload.user }
                    newUser.personal_api_keys = payload.user.personal_api_keys.filter(
                        (current_key: PersonalAPIKeyType) => current_key.id !== payload.key.id
                    )
                    return newUser
                },
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: actions.loadUser,
    }),

    selectors: ({ selectors }) => ({
        eventProperties: [
            () => [selectors.user],
            (user) =>
                user?.team.event_properties.map(
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

    listeners: ({ actions, selectors }) => ({
        loadUser: async () => {
            try {
                const user = await api.get('api/user')
                actions.setUser(user)

                if (user && user.id) {
                    const Sentry = (window as any).Sentry
                    Sentry?.setUser({
                        email: user.email,
                        id: user.id,
                    })

                    const PostHog = (window as any).posthog
                    if (PostHog) {
                        PostHog.identify(user.distinct_id)
                        PostHog.register({
                            posthog_version: user.posthog_version,
                            has_slack_webhook: !!user.team?.slack_incoming_webhook,
                        })
                    }
                }
            } catch {
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
        createPersonalAPIKeyRequest: async ({ label }) => {
            try {
                const newKey = await api.create('api/personal_api_key/', { label })
                actions.createPersonalAPIKeySuccess(selectors.user(), newKey)
            } catch {
                actions.createPersonalAPIKeyFailure(label)
            }
        },
        createPersonalAPIKeySuccess: ({ key }: { key: PersonalAPIKeyType }) => {
            toast(<div className="text-success">Personal API key "{key.label}" successfully created</div>)
        },
        createPersonalAPIKeyFailure: ({ label }: { label: string }) => {
            toast(<div className="text-danger">Could not create personal API key "{label}"</div>)
        },
        deletePersonalAPIKeyRequest: async ({ key }: { key: PersonalAPIKeyType }) => {
            try {
                await api.delete(`api/personal_api_key/${key.id}/`)
                actions.deletePersonalAPIKeySuccess(selectors.user(), key)
            } catch {
                actions.deletePersonalAPIKeyFailure(key)
            }
        },
        deletePersonalAPIKeySuccess: ({ key }) => {
            toast(<div className="text-success">Personal API key "{key.label}" successfully deleted</div>)
        },
        deletePersonalAPIKeyFailure: ({ key }) => {
            toast(<div className="text-danger">Could not delete personal API key "{key.label}"</div>)
        },
    }),
})

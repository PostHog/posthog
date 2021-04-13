import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { userLogicType } from './userLogicType'
import { UserType, UserUpdateType } from '~/types'
import posthog from 'posthog-js'
import { toast } from 'react-toastify'

export const userLogic = kea<userLogicType<UserType, UserUpdateType>>({
    actions: () => ({
        loadUser: (resetOnFailure?: boolean) => ({ resetOnFailure }),
        updateCurrentTeam: (teamId: number, destination?: string) => ({ teamId, destination }),
        updateCurrentOrganization: (organizationId: string, destination?: string) => ({ organizationId, destination }),
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
        userUpdateLoading: [
            false,
            {
                userUpdateRequest: () => true,
                userUpdateSuccess: () => false,
                userUpdateFailure: () => false,
            },
        ],
        userLoading: [
            false,
            {
                setUserLoading: (_, { loading }) => loading,
            },
        ],
    },
    selectors: ({ selectors }) => ({
        demoOnlyProject: [
            () => [selectors.user],
            (user): boolean =>
                (user?.team?.is_demo && user?.organization?.teams && user.organization.teams.length == 1) || false,
        ],
    }),
    loaders: ({ values }) => ({
        user: [
            null as UserType | null,
            {
                loadUser: async () => {
                    try {
                        const user: UserType = await api.get('api/users/@me/')

                        if (user && user.id) {
                            const Sentry = (window as any).Sentry
                            Sentry?.setUser({
                                email: user.email,
                                id: user.id,
                            })

                            if (posthog) {
                                // If user is not anonymous and the distinct id is different from the current one, reset
                                if (
                                    posthog.get_property('$device_id') !== posthog.get_distinct_id() &&
                                    posthog.get_distinct_id() !== user.distinct_id
                                ) {
                                    posthog.reset()
                                }

                                posthog.identify(user.distinct_id)
                                posthog.people.set({ email: user.anonymize_data ? null : user.email })

                                posthog.register({
                                    is_demo_project: user.team?.is_demo,
                                })
                            }
                        }
                        return user
                    } catch (e) {
                        console.error(e)
                    }
                    return null
                },
                updateUser: async (payload: Partial<UserType>) => {
                    if (!values.user) {
                        throw new Error('Current user has not been loaded yet, so it cannot be updated!')
                    }
                    return await api.update('api/users/@me/', payload)
                },
            },
        ],
    }),
    listeners: ({ values }) => ({
        logout: () => {
            posthog.reset()
            window.location.href = '/logout'
        },
        updateUserSuccess: () => {
            toast.dismiss('updateUser')
            toast.success(
                <div>
                    <h1>Your preferences have been saved!</h1>
                    <p>All set. Click here to dismiss.</p>
                </div>,
                {
                    toastId: 'updateUser',
                }
            )
        },
        updateCurrentTeam: async ({ teamId, destination }, breakpoint) => {
            if (values.user?.team?.id === teamId) {
                return
            }
            await breakpoint(10)
            await api.update('api/users/@me/', { set_current_team: teamId })
            window.location.href = destination || '/'
        },
        updateCurrentOrganization: async ({ organizationId, destination }, breakpoint) => {
            if (values.user?.organization?.id === organizationId) {
                return
            }
            await breakpoint(10)
            await api.update('api/users/@me/', { set_current_organization: organizationId })
            window.location.href = destination || '/'
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadUser],
    }),
})

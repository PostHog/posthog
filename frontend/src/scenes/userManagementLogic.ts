import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { ProductKey, UserType } from '~/types'
import { forms } from 'kea-forms'

import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { userManagementLogicType } from './userManagementLogicType'
import { userLogic } from './userLogic'
import { DashboardCompatibleScenes } from './sceneTypes'

export interface UserDetailsFormType {
    first_name: string
    email: string
}

export const userManagementLogic = kea<userManagementLogicType>([
    path(['scenes', 'userManagementLogic']),
    connect({
        values: [preflightLogic, ['preflight'], userLogic, ['user', 'userLoading']],
        actions: [userLogic, ['setUser', 'setUserLoading']],
    }),
    actions(() => ({
        loadUser: true,
        updateUser: (user: Partial<UserType>, successCallback?: () => void) => ({ user, successCallback }),
        setUserScenePersonalisation: (scene: DashboardCompatibleScenes, dashboard: number) => ({ scene, dashboard }),
        updateUserSuccess: true,
        updateCurrentTeam: (teamId: number, destination?: string) => ({ teamId, destination }),
        updateCurrentOrganization: (organizationId: string, destination?: string) => ({ organizationId, destination }),
        updateHasSeenProductIntroFor: (productKey: ProductKey, value: boolean) => ({ productKey, value }),
    })),
    forms(({ actions }) => ({
        userDetails: {
            errors: ({ first_name, email }) => ({
                first_name: !first_name
                    ? 'You need to have a name.'
                    : first_name.length > 150
                    ? 'This name is too long. Please keep it under 151 characters.'
                    : null,
                email: !email
                    ? 'You need to have an email.'
                    : first_name.length > 254
                    ? 'This email is too long. Please keep it under 255 characters.'
                    : null,
            }),
            submit: (user) => {
                actions.updateUser(user)
            },
        },
    })),

    reducers({
        userDetails: [
            {} as UserDetailsFormType,
            {
                loadUserSuccess: (_, { user }) => ({
                    first_name: user?.first_name || '',
                    email: user?.email || '',
                }),
                setUser: (_, { user }) => ({
                    first_name: user?.first_name || '',
                    email: user?.email || '',
                }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadUser: async () => {
            actions.setUserLoading(true)
            try {
                const user = await api.get('api/users/@me/')
                actions.setUser(user)
            } catch (error: any) {
                console.error(error)
                lemonToast.error(`Error loading user`)
            }
            actions.setUserLoading(false)
        },
        updateUser: async ({ user, successCallback }) => {
            if (!values.user) {
                throw new Error('Current user has not been loaded yet, so it cannot be updated!')
            }
            try {
                const response = await api.update('api/users/@me/', user)
                successCallback && successCallback()
                actions.setUser(response)
                actions.updateUserSuccess()
            } catch (error: any) {
                console.error(error)
                lemonToast.error(`Error saving preferences`, {
                    toastId: 'updateUser',
                })
            }
        },
        setUserScenePersonalisation: async ({ scene, dashboard }) => {
            if (!values.user) {
                throw new Error('Current user has not been loaded yet, so it cannot be updated!')
            }
            try {
                const response = await api.create('api/users/@me/scene_personalisation', {
                    scene,
                    dashboard,
                })

                actions.setUser(response)
                actions.updateUserSuccess()
            } catch (error: any) {
                console.error(error)
                lemonToast.error(`Error saving preferences`, {
                    toastId: 'updateUser',
                })
            }
        },
        updateUserSuccess: () => {
            lemonToast.dismiss('updateUser')
            lemonToast.success('Preferences saved', {
                toastId: 'updateUser',
            })
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
        updateHasSeenProductIntroFor: async ({ productKey, value }, breakpoint) => {
            await breakpoint(10)
            await api
                .update('api/users/@me/', {
                    has_seen_product_intro_for: {
                        ...values.user?.has_seen_product_intro_for,
                        [productKey]: value,
                    },
                })
                .then(() => {
                    actions.loadUser()
                })
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.user) {
            // Nothing to do
        } else if (values.user === null) {
            actions.loadUserFailure('Logged out')
        } else {
            actions.loadUser()
        }
    }),
])

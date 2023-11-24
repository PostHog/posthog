import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardCompatibleScenes } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { getAppContext } from 'lib/utils/getAppContext'
import posthog from 'posthog-js'

import { AvailableFeature, OrganizationBasicType, ProductKey, UserType } from '~/types'

import type { userLogicType } from './userLogicType'

export interface UserDetailsFormType {
    first_name: string
    email: string
}

export const userLogic = kea<userLogicType>([
    path(['scenes', 'userLogic']),
    actions(() => ({
        loadUser: (resetOnFailure?: boolean) => ({ resetOnFailure }),
        updateCurrentTeam: (teamId: number, destination?: string) => ({ teamId, destination }),
        updateCurrentOrganization: (organizationId: string, destination?: string) => ({ organizationId, destination }),
        logout: true,
        updateUser: (user: Partial<UserType>, successCallback?: () => void) => ({ user, successCallback }),
        setUserScenePersonalisation: (scene: DashboardCompatibleScenes, dashboard: number) => ({ scene, dashboard }),
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
    loaders(({ values, actions }) => ({
        user: [
            // TODO: Because we don't actually load the app until this request completes, `user` is never `null` (will help simplify checks across the app)
            null as UserType | null,
            {
                loadUser: async () => {
                    try {
                        return await api.get('api/users/@me/')
                    } catch (error: any) {
                        console.error(error)
                        actions.loadUserFailure(error.message)
                    }
                    return null
                },
                updateUser: async ({ user, successCallback }) => {
                    if (!values.user) {
                        throw new Error('Current user has not been loaded yet, so it cannot be updated!')
                    }
                    try {
                        const response = await api.update('api/users/@me/', user)
                        successCallback && successCallback()
                        return response
                    } catch (error: any) {
                        console.error(error)
                        actions.updateUserFailure(error.message)
                    }
                },
                setUserScenePersonalisation: async ({ scene, dashboard }) => {
                    if (!values.user) {
                        throw new Error('Current user has not been loaded yet, so it cannot be updated!')
                    }
                    try {
                        return await api.create('api/users/@me/scene_personalisation', {
                            scene,
                            dashboard,
                        })
                    } catch (error: any) {
                        console.error(error)
                        actions.updateUserFailure(error.message)
                    }
                },
            },
        ],
    })),
    reducers({
        userDetails: [
            {} as UserDetailsFormType,
            {
                loadUserSuccess: (_, { user }) => ({
                    first_name: user?.first_name || '',
                    email: user?.email || '',
                }),
                updateUserSuccess: (_, { user }) => ({
                    first_name: user?.first_name || '',
                    email: user?.email || '',
                }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        logout: () => {
            posthog.reset()
            window.location.href = '/logout'
        },
        loadUserSuccess: ({ user }) => {
            if (user && user.uuid) {
                const Sentry = (window as any).Sentry
                Sentry?.setUser({
                    email: user.email,
                    id: user.uuid,
                })

                if (posthog) {
                    posthog.identify(user.distinct_id)
                    posthog.people.set({
                        email: user.anonymize_data ? null : user.email,
                        realm: user.realm,
                    })

                    posthog.register({
                        is_demo_project: user.team?.is_demo,
                    })

                    if (user.team) {
                        posthog.group('project', user.team.uuid, {
                            id: user.team.id,
                            uuid: user.team.uuid,
                            name: user.team.name,
                            ingested_event: user.team.ingested_event,
                            is_demo: user.team.is_demo,
                            timezone: user.team.timezone,
                            instance_tag: user.organization?.metadata?.instance_tag,
                        })
                    }

                    if (user.organization) {
                        posthog.group('organization', user.organization.id, {
                            id: user.organization.id,
                            name: user.organization.name,
                            slug: user.organization.slug,
                            created_at: user.organization.created_at,
                            available_features: user.organization.available_features,
                            ...user.organization.metadata,
                        })

                        if (user.organization.customer_id) {
                            posthog.group('customer', user.organization.customer_id)
                        }
                    }
                }
            }
        },
        updateUserSuccess: () => {
            lemonToast.dismiss('updateUser')
            lemonToast.success('Preferences saved', {
                toastId: 'updateUser',
            })
        },
        updateUserFailure: () => {
            lemonToast.error(`Error saving preferences`, {
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
    selectors({
        hasAvailableFeature: [
            (s) => [s.user],
            (user) => {
                return (feature: AvailableFeature, currentUsage?: number) => {
                    const availableProductFeatures = user?.organization?.available_product_features
                    if (availableProductFeatures && availableProductFeatures.length > 0) {
                        const availableFeature = availableProductFeatures.find((obj) => obj.key === feature)
                        return availableFeature
                            ? currentUsage
                                ? availableFeature?.limit
                                    ? availableFeature?.limit > currentUsage
                                    : true
                                : true
                            : false
                    }
                    // if we don't have the new available_product_features obj, fallback to old available_features
                    return !!user?.organization?.available_features.includes(feature)
                }
            },
        ],
        otherOrganizations: [
            (s) => [s.user],
            (user): OrganizationBasicType[] =>
                user
                    ? user.organizations
                          ?.filter((organization) => organization.id !== user.organization?.id)
                          .sort((orgA, orgB) =>
                              orgA.id === user?.organization?.id ? -2 : orgA.name.localeCompare(orgB.name)
                          ) || []
                    : [],
        ],
    }),
    afterMount(({ actions }) => {
        const preloadedUser = getAppContext()?.current_user
        if (preloadedUser) {
            actions.loadUserSuccess(preloadedUser)
        } else if (preloadedUser === null) {
            actions.loadUserFailure('Logged out')
        } else {
            actions.loadUser()
        }
    }),
])

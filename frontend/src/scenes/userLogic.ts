import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { AvailableFeature, OrganizationBasicType, UserType } from '~/types'
import posthog from 'posthog-js'

import { getAppContext } from 'lib/utils/getAppContext'
import type { userLogicType } from './userLogicType'

export interface UserDetailsFormType {
    first_name: string
    email: string
}

export const userLogic = kea<userLogicType>([
    path(['scenes', 'userLogic']),
    actions({
        logout: true,
        setUser: (user: UserType | null) => ({ user }),
        setUserLoading: (loading: boolean) => ({ loading }),
    }),
    reducers({
        user: [
            null as UserType | null,
            {
                setUser: (_, { user }) => user,
            },
        ],

        userLoading: [
            false,
            {
                setUser: () => false,
                setUserLoading: (_, { loading }) => loading,
            },
        ],
    }),
    listeners({
        logout: () => {
            posthog.reset()
            window.location.href = '/logout'
        },
        setUser: ({ user }) => {
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
    }),
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
            actions.setUser(preloadedUser)
        }
    }),
])

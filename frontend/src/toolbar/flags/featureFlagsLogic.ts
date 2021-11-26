import { kea } from 'kea'
import { CombinedFeatureFlagAndOverrideType } from '~/types'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { toolbarFetch } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import Fuse from 'fuse.js'
import { PostHog } from 'posthog-js'
import { posthog } from '~/toolbar/posthog'
import { encodeParams } from 'kea-router'

export const featureFlagsLogic = kea<featureFlagsLogicType>({
    path: ['toolbar', 'flags', 'featureFlagsLogic'],
    actions: {
        getUserFlags: true,
        setOverriddenUserFlag: (flagId: number, overrideValue: string | boolean) => ({ flagId, overrideValue }),
        deleteOverriddenUserFlag: (overrideId: number) => ({ overrideId }),
        setShowLocalFeatureFlagWarning: (showWarning: boolean) => ({ showWarning }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    },

    loaders: ({ values }) => ({
        userFlags: [
            [] as CombinedFeatureFlagAndOverrideType[],
            {
                getUserFlags: async (_, breakpoint) => {
                    const params = {
                        groups: getGroups(toolbarLogic.values.posthog),
                    }
                    const response = await toolbarFetch(
                        `/api/projects/@current/feature_flags/my_flags${encodeParams(params, '?')}`
                    )

                    if (response.status >= 400) {
                        toolbarLogic.actions.tokenExpired()
                        return []
                    }

                    breakpoint()
                    if (!response.ok) {
                        return []
                    }
                    return await response.json()
                },
                setOverriddenUserFlag: async ({ flagId, overrideValue }, breakpoint) => {
                    const response = await toolbarFetch(
                        '/api/projects/@current/feature_flag_overrides/my_overrides',
                        'POST',
                        {
                            feature_flag: flagId,
                            override_value: overrideValue,
                        }
                    )
                    breakpoint()
                    if (!response.ok) {
                        return []
                    }
                    const results = await response.json()

                    posthog.capture('toolbar feature flag overridden')
                    toolbarLogic.values.posthog?.featureFlags.reloadFeatureFlags()
                    return [...values.userFlags].map((userFlag) =>
                        userFlag.feature_flag.id === results.feature_flag
                            ? { ...userFlag, override: results }
                            : userFlag
                    )
                },
                deleteOverriddenUserFlag: async ({ overrideId }, breakpoint) => {
                    const response = await toolbarFetch(
                        `/api/projects/@current/feature_flag_overrides/${overrideId}`,
                        'DELETE'
                    )
                    breakpoint()
                    if (!response.ok) {
                        return []
                    }

                    posthog.capture('toolbar feature flag override removed')
                    toolbarLogic.values.posthog?.featureFlags.reloadFeatureFlags()
                    return [...values.userFlags].map((userFlag) =>
                        userFlag?.override?.id === overrideId ? { ...userFlag, override: null } : userFlag
                    )
                },
            },
        ],
    }),
    reducers: {
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        showLocalFeatureFlagWarning: [
            false,
            {
                setShowLocalFeatureFlagWarning: (_, { showWarning }) => showWarning,
            },
        ],
    },
    selectors: {
        userFlagsWithCalculatedInfo: [
            (s) => [s.userFlags],
            (userFlags) => {
                return userFlags.map((flag) => {
                    const hasVariants = (flag.feature_flag.filters?.multivariate?.variants?.length || 0) > 0
                    const currentValue = flag.override
                        ? flag.override.override_value
                        : flag.value_for_user_without_override

                    return {
                        ...flag,
                        hasVariants,
                        currentValue,
                    }
                })
            },
        ],
        filteredFlags: [
            (s) => [s.searchTerm, s.userFlagsWithCalculatedInfo],
            (searchTerm, userFlagsWithCalculatedInfo) => {
                return searchTerm
                    ? new Fuse(userFlagsWithCalculatedInfo, {
                          threshold: 0.3,
                          keys: ['feature_flag.key', 'feature_flag.name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : userFlagsWithCalculatedInfo
            },
        ],
        countFlagsOverridden: [(s) => [s.userFlags], (userFlags) => userFlags.filter((flag) => !!flag.override).length],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.getUserFlags()
            const { posthog: clientPostHog } = toolbarLogic.values
            if (clientPostHog) {
                const locallyOverrideFeatureFlags = clientPostHog.get_property('$override_feature_flags')
                if (locallyOverrideFeatureFlags) {
                    actions.setShowLocalFeatureFlagWarning(true)
                }
            }
        },
    }),
})

function getGroups(posthogInstance: PostHog | null): Record<string, any> {
    try {
        return posthogInstance?.getGroups() || {}
    } catch {
        return {}
    }
}

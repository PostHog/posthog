import { kea } from 'kea'
import { CombinedFeatureFlagAndOverrideType } from '~/types'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { PostHog } from 'posthog-js'
import { toolbarFetch } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import Fuse from 'fuse.js'

export const featureFlagsLogic = kea<featureFlagsLogicType>({
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
                    const response = await toolbarFetch('/api/feature_flag/my_flags')
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

                    ;(window['posthog'] as PostHog).featureFlags.reloadFeatureFlags()
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

                    ;(window['posthog'] as PostHog).featureFlags.reloadFeatureFlags()
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
        flagNames: [(s) => [s.userFlags], (userFlags) => userFlags.map((uf) => uf.feature_flag.name)],
        searchMatches: [
            (s) => [s.searchTerm, s.flagNames],
            (searchTerm, flagNames) =>
                searchTerm
                    ? new Fuse(flagNames, {
                          threshold: 0.3,
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : flagNames,
        ],
        isHiddenBySearch: [
            (s) => [s.searchMatches],
            (searchMatches) => (featureFlagName: string) => !searchMatches.includes(featureFlagName),
        ],
        countFlagsOverridden: [(s) => [s.userFlags], (userFlags) => userFlags.filter((flag) => !!flag.override).length],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.getUserFlags()
            if (window && window['posthog']) {
                ;(window['posthog'] as PostHog).onFeatureFlags((_, variants) => {
                    if (variants) {
                        toolbarLogic.actions.updateFeatureFlags(variants)
                    }
                })
                const locallyOverrideFeatureFlags = (window['posthog'] as PostHog).get_property(
                    '$override_feature_flags'
                )
                if (locallyOverrideFeatureFlags) {
                    actions.setShowLocalFeatureFlagWarning(true)
                }
            }
        },
    }),
})

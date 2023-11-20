import { loaders } from 'kea-loaders'
import { kea, path, connect, actions, reducers, selectors, listeners, events } from 'kea'
import { CombinedFeatureFlagAndValueType } from '~/types'
import type { featureFlagsLogicType } from './featureFlagsLogicType'
import { toolbarFetch } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import Fuse from 'fuse.js'
import type { PostHog } from 'posthog-js'
import { posthog } from '~/toolbar/posthog'
import { encodeParams } from 'kea-router'

export const featureFlagsLogic = kea<featureFlagsLogicType>([
    path(['toolbar', 'flags', 'featureFlagsLogic']),
    connect(() => [toolbarLogic]),
    actions({
        getUserFlags: true,
        setOverriddenUserFlag: (flagKey: string, overrideValue: string | boolean) => ({ flagKey, overrideValue }),
        deleteOverriddenUserFlag: (flagKey: string) => ({ flagKey }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        checkLocalOverrides: true,
        storeLocalOverrides: (localOverrides: Record<string, string | boolean>) => ({ localOverrides }),
    }),
    loaders(() => ({
        userFlags: [
            [] as CombinedFeatureFlagAndValueType[],
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
            },
        ],
    })),
    reducers({
        localOverrides: [
            {} as Record<string, string | boolean>,
            {
                storeLocalOverrides: (_, { localOverrides }) => localOverrides,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors({
        userFlagsWithOverrideInfo: [
            (s) => [s.userFlags, s.localOverrides],
            (userFlags, localOverrides) => {
                return userFlags.map((flag) => {
                    const hasVariants = (flag.feature_flag.filters?.multivariate?.variants?.length || 0) > 0

                    const currentValue =
                        flag.feature_flag.key in localOverrides ? localOverrides[flag.feature_flag.key] : flag.value

                    return {
                        ...flag,
                        hasVariants,
                        currentValue,
                        hasOverride: flag.feature_flag.key in localOverrides,
                    }
                })
            },
        ],
        filteredFlags: [
            (s) => [s.searchTerm, s.userFlagsWithOverrideInfo],
            (searchTerm, userFlagsWithOverrideInfo) => {
                return searchTerm
                    ? new Fuse(userFlagsWithOverrideInfo, {
                          threshold: 0.3,
                          keys: ['feature_flag.key', 'feature_flag.name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : userFlagsWithOverrideInfo
            },
        ],
        countFlagsOverridden: [(s) => [s.localOverrides], (localOverrides) => Object.keys(localOverrides).length],
    }),
    listeners(({ actions, values }) => ({
        checkLocalOverrides: () => {
            const { posthog: clientPostHog } = toolbarLogic.values
            if (clientPostHog) {
                const locallyOverrideFeatureFlags = clientPostHog.get_property('$override_feature_flags') || {}
                actions.storeLocalOverrides(locallyOverrideFeatureFlags)
            }
        },
        setOverriddenUserFlag: ({ flagKey, overrideValue }) => {
            const { posthog: clientPostHog } = toolbarLogic.values
            if (clientPostHog) {
                clientPostHog.featureFlags.override({ ...values.localOverrides, [flagKey]: overrideValue })
                posthog.capture('toolbar feature flag overridden')
                actions.checkLocalOverrides()
                toolbarLogic.values.posthog?.featureFlags.reloadFeatureFlags()
            }
        },
        deleteOverriddenUserFlag: ({ flagKey }) => {
            const { posthog: clientPostHog } = toolbarLogic.values
            if (clientPostHog) {
                const updatedFlags = { ...values.localOverrides }
                delete updatedFlags[flagKey]
                if (Object.keys(updatedFlags).length > 0) {
                    clientPostHog.featureFlags.override({ ...updatedFlags })
                } else {
                    clientPostHog.featureFlags.override(false)
                }
                posthog.capture('toolbar feature flag override removed')
                actions.checkLocalOverrides()
                toolbarLogic.values.posthog?.featureFlags.reloadFeatureFlags()
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.getUserFlags()
            actions.checkLocalOverrides()
        },
    })),
])

function getGroups(posthogInstance: PostHog | null): Record<string, any> {
    try {
        return posthogInstance?.getGroups() || {}
    } catch {
        return {}
    }
}

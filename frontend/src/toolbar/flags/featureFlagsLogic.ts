import { kea } from 'kea'
import { FeatureFlagType } from '~/types'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { PostHog } from 'posthog-js'
import { toolbarFetch } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export const featureFlagsLogic = kea<featureFlagsLogicType>({
    actions: {
        getUserFlags: true,
        getOverriddenFlags: true,
        setFeatureFlags: (flags: Record<string, string | boolean>) => ({ flags }),
        setOverriddenFlag: (flag: number, override_value: string | boolean) => ({ flag, override_value }),
    },

    reducers: {
        overriddenFlags: [
            {} as Record<string, string | boolean>,
            {
                // this overrides the loader, so we would have instant feedback in the UI
                setOverriddenFlag: (state, { flag, override_value }) => ({ ...state, [flag]: override_value }),
            },
        ],
        enabledFeatureFlags: [
            {} as Record<string, string | boolean>,
            {
                setFeatureFlags: (_, { flags }) => flags,
            },
        ],
    },

    loaders: ({ values }) => ({
        userFlags: [
            {} as Record<string, string | boolean>,
            {
                getUserFlags: async (_, breakpoint) => {
                    const response = await toolbarFetch('api/feature_flag/my_flags')
                    breakpoint()
                    if (response.status === 403) {
                        return {}
                    }
                    const results = await response.json()
                    return results.flags
                },
            },
        ],
        overriddenFlags: {
            getOverriddenFlags: async (_, breakpoint) => {
                const response = await toolbarFetch('api/feature_flag_override/my_overrides')
                breakpoint()
                if (response.status === 403) {
                    return {}
                }
                const results = await response.json()
                return results.feature_flag_overrides
            },
            setOverriddenFlag: async ({ flag, override_value }, breakpoint) => {
                const response = await toolbarFetch('api/feature_flag_override/my_overrides', {
                    feature_flag: flag,
                    override_value: override_value,
                })
                breakpoint()
                if (response.status === 403) {
                    return {}
                }
                const results = await response.json()
                ;(window['posthog'] as PostHog).featureFlags.reloadFeatureFlags()
                return { ...values.overriddenFlags, ...results }
            },
        },
        allFeatureFlags: [
            [] as FeatureFlagType[],
            {
                // eslint-disable-next-line
                getFlags: async (_ = null, breakpoint: () => void) => {
                    const response = await toolbarFetch('api/feature_flag/')
                    breakpoint()
                    if (response.status === 403) {
                        return []
                    }
                    const results = await response.json()
                    if (!Array.isArray(results?.results)) {
                        throw new Error('Error loading feature flags!')
                    }

                    return results.results
                },
            },
        ],
    }),

    selectors: {
        combinedFlags: [
            (s) => [s.userFlags, s.overriddenFlags],
            (userFlags, overriddenFlags) => ({ ...userFlags, ...overriddenFlags }),
        ],
        sortedFeatureFlags: [
            (s) => [s.allFeatureFlags],
            (allFeatureFlags): FeatureFlagType[] =>
                [...allFeatureFlags].sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')),
        ],
        featureFlagCount: [(s) => [s.sortedFeatureFlags], (sortedFeatureFlags) => sortedFeatureFlags.length],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.getFlags()
            actions.getUserFlags()
            actions.getOverriddenFlags()
            ;(window['posthog'] as PostHog).onFeatureFlags((_, variants) => {
                actions.setFeatureFlags(variants)
                toolbarLogic.actions.updateFeatureFlags(variants)
            })
        },
    }),
})

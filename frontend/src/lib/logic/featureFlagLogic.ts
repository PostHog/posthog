/*
    This module allows us to **use** feature flags in PostHog.

    Use this instead of `window.posthog.isFeatureEnabled('feature')`
*/
import { kea } from 'kea'
import { PostHog } from 'posthog-js'
import { featureFlagLogicType } from 'types/lib/logic/featureFlagLogicType'
import posthog from 'posthog-js'

type FeatureFlagsSet = { [flag: string]: boolean }

export const featureFlagLogic = kea<featureFlagLogicType<PostHog, FeatureFlagsSet>>({
    actions: {
        setFeatureFlags: (featureFlags: string[]) => ({ featureFlags }),
    },

    reducers: {
        featureFlags: [
            {} as FeatureFlagsSet,
            {
                setFeatureFlags: (_: FeatureFlagsSet, { featureFlags }: { featureFlags: string[] }) => {
                    const flags: FeatureFlagsSet = {}
                    for (const flag of featureFlags) {
                        flags[flag] = true
                    }
                    return flags
                },
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            posthog.onFeatureFlags(actions.setFeatureFlags)
        },
    }),
})

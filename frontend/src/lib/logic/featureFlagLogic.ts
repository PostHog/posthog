/*
    This module allows us to **use** feature flags in PostHog.

    Use this instead of `window.posthog.isFeatureEnabled('feature')`
*/
import { kea } from 'kea'
import { PostHog } from 'posthog-js'
import { featureFlagLogicType } from 'types/lib/logic/featureFlagLogicType'

type FeatureFlagsSet = { [flag: string]: boolean }

export const featureFlagLogic = kea<featureFlagLogicType<PostHog, FeatureFlagsSet>>({
    actions: {
        posthogFound: (posthog: PostHog) => ({ posthog }),
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

    listeners: ({ actions }) => ({
        posthogFound: ({ posthog }: { posthog: PostHog }) => {
            posthog.onFeatureFlags(actions.setFeatureFlags)
        },
    }),

    events: ({ actions, cache }) => ({
        afterMount: () => {
            if (typeof window !== 'undefined') {
                if (window.posthog) {
                    actions.posthogFound(window.posthog)
                } else {
                    // check every 300ms if posthog is now there
                    cache.posthogInterval = window.setInterval(() => {
                        if (window.posthog) {
                            actions.posthogFound(window.posthog)
                            window.clearInterval(cache.posthogInterval)
                        }
                    }, 300)
                }
            }
        },
        beforeUnmount: () => {
            if (typeof window !== 'undefined') {
                window.clearInterval(cache.posthogInterval)
            }
        },
    }),
})

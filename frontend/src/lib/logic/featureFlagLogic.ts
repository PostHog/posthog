/*
    This module allows us to **use** feature flags in PostHog.

    Use this instead of `window.posthog.isFeatureEnabled('feature')`
*/
import { kea } from 'kea'
import { PostHog } from 'posthog-js'
import { featureFlagLogicType } from 'types/lib/logic/featureFlagLogicType'
import posthog from 'posthog-js'

type FeatureFlagsSet = { [flag: string]: boolean }

const eventsNotified: Record<string, boolean> = {}
function notifyFlagIfNeeded(flag: string, flagState: boolean): void {
    if (!eventsNotified[flag]) {
        posthog.capture('$feature_flag_called', {
            $feature_flag: flag,
            $feature_flag_response: flagState,
        })
        eventsNotified[flag] = true
    }
}

function spyOnFeatureFlags(featureFlags: FeatureFlagsSet): FeatureFlagsSet {
    if (typeof window.Proxy !== 'undefined') {
        return new Proxy(
            {},
            {
                get(_, flag) {
                    const flagString = flag.toString()
                    notifyFlagIfNeeded(flagString, !!featureFlags[flagString])
                    return featureFlags[flagString]
                },
            }
        )
    } else {
        const flags: FeatureFlagsSet = {}
        for (const flag of Object.keys(featureFlags)) {
            Object.defineProperty(flags, flag, {
                get: function () {
                    notifyFlagIfNeeded(flag, true)
                    return true
                },
            })
        }
        return flags
    }
}

export const featureFlagLogic = kea<featureFlagLogicType<PostHog, FeatureFlagsSet>>({
    actions: {
        setFeatureFlags: (featureFlags: string[]) => ({ featureFlags }),
    },

    reducers: {
        featureFlags: [
            {} as FeatureFlagsSet,
            {
                setFeatureFlags: (_, { featureFlags }) => {
                    const flags: FeatureFlagsSet = {}
                    for (const flag of featureFlags) {
                        flags[flag] = true
                    }
                    return spyOnFeatureFlags(flags)
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

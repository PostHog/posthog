/*
    This module allows us to **use** feature flags in PostHog.

    Use this instead of `window.posthog.isFeatureEnabled('feature')`
*/
import { kea } from 'kea'
import { PostHog } from 'posthog-js'
import { featureFlagLogicType } from './featureFlagLogicType'
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
                    const flagState = !!featureFlags[flagString]
                    notifyFlagIfNeeded(flagString, flagState)
                    return flagState
                },
            }
        )
    } else {
        // Fallback for IE11. Won't track "false" results. ¯\_(ツ)_/¯
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

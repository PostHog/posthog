/*
    This module allows us to **use** feature flags in PostHog.

    Use this instead of `window.posthog.isFeatureEnabled('feature')`
*/
import { kea } from 'kea'
import { featureFlagLogicType } from './featureFlagLogicType'
import posthog from 'posthog-js'
import { getAppContext } from 'lib/utils/getAppContext'

type FeatureFlagsSet = {
    [flag: string]: boolean
}
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
    const persistedFeatureFlags = getAppContext()?.persist_feature_flags || []
    const combinedFlags = { ...featureFlags, ...Object.fromEntries(persistedFeatureFlags.map((f) => [f, true])) }

    if (typeof window.Proxy !== 'undefined') {
        return new Proxy(
            {},
            {
                get(_, flag) {
                    if (flag === 'toJSON') {
                        return JSON.stringify(combinedFlags)
                    }
                    const flagString = flag.toString()
                    const flagState = !!combinedFlags[flagString]
                    notifyFlagIfNeeded(flagString, flagState)
                    return flagState
                },
            }
        )
    } else {
        // Fallback for IE11. Won't track "false" results. ¯\_(ツ)_/¯
        const flags: FeatureFlagsSet = {}
        for (const flag of Object.keys(combinedFlags)) {
            Object.defineProperty(flags, flag, {
                get: function () {
                    if (flag === 'toJSON') {
                        return JSON.stringify(combinedFlags)
                    }
                    notifyFlagIfNeeded(flag, true)
                    return true
                },
            })
        }
        return flags
    }
}

export const featureFlagLogic = kea<featureFlagLogicType<FeatureFlagsSet>>({
    actions: {
        setFeatureFlags: (featureFlags: string[]) => ({ featureFlags }),
    },

    reducers: {
        featureFlags: [
            {} as FeatureFlagsSet,
            { persist: true },
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
        receivedFeatureFlags: [
            false,
            {
                setFeatureFlags: () => true,
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            posthog.onFeatureFlags(actions.setFeatureFlags)
        },
    }),
})

/*
    This module allows us to **use** feature flags in PostHog.

    Use this instead of `window.posthog.isFeatureEnabled('feature')`
*/
import { kea } from 'kea'
import { featureFlagLogicType } from './featureFlagLogicType'
import posthog from 'posthog-js'
import { getAppContext } from 'lib/utils/getAppContext'

export type FeatureFlagsSet = {
    [flag: string]: boolean | string
}
const eventsNotified: Record<string, boolean> = {}
function notifyFlagIfNeeded(flag: string, flagState: string | boolean): void {
    if (!eventsNotified[flag]) {
        posthog.capture('$feature_flag_called', {
            $feature_flag: flag,
            $feature_flag_response: flagState,
        })
        eventsNotified[flag] = true
    }
}

function getPersistedFeatureFlags(): FeatureFlagsSet {
    const persistedFeatureFlags = getAppContext()?.persisted_feature_flags || []
    return Object.fromEntries(persistedFeatureFlags.map((f) => [f, true]))
}

function spyOnFeatureFlags(featureFlags: FeatureFlagsSet): FeatureFlagsSet {
    const persistedFlags = getPersistedFeatureFlags()
    const availableFlags = Object.keys(persistedFlags).length ? persistedFlags : featureFlags

    if (typeof window.Proxy !== 'undefined') {
        return new Proxy(
            {},
            {
                get(_, flag) {
                    if (flag === 'toJSON') {
                        return () => availableFlags
                    }
                    const flagString = flag.toString()
                    const flagState = availableFlags[flagString]
                    notifyFlagIfNeeded(flagString, flagState)
                    return flagState
                },
            }
        )
    } else {
        // Fallback for IE11. Won't track "false" results. ¯\_(ツ)_/¯
        const flags: FeatureFlagsSet = {}
        for (const flag of Object.keys(availableFlags)) {
            Object.defineProperty(flags, flag, {
                get: function () {
                    if (flag === 'toJSON') {
                        return () => availableFlags
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
    path: ['lib', 'logic', 'featureFlagLogic'],
    actions: {
        setFeatureFlags: (flags: string[], variants: Record<string, string | boolean>) => ({ flags, variants }),
    },

    reducers: {
        featureFlags: [
            getPersistedFeatureFlags(),
            { persist: true },
            {
                setFeatureFlags: (_, { variants }) => spyOnFeatureFlags(variants),
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

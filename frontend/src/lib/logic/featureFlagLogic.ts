import { actions, afterMount, kea, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { FeatureFlagKey } from 'lib/constants'
import { getAppContext } from 'lib/utils/getAppContext'

import { AppContext } from '~/types'

import type { featureFlagLogicType } from './featureFlagLogicType'

export type FeatureFlagsSet = {
    [flag in FeatureFlagKey]?: boolean | string
}
const eventsNotified: Record<string, boolean> = {}
function notifyFlagIfNeeded(flag: string, flagState: string | boolean | undefined): void {
    if (!eventsNotified[flag]) {
        posthog.capture('$feature_flag_called', {
            $feature_flag: flag,
            $feature_flag_response: flagState === undefined ? false : flagState,
        })
        eventsNotified[flag] = true
    }
}

function getPersistedFeatureFlags(appContext: AppContext | undefined = getAppContext()): FeatureFlagsSet {
    const persistedFeatureFlags = appContext?.persisted_feature_flags || []
    const flags = Object.fromEntries(
        persistedFeatureFlags.map((f) => {
            return [f, true]
        })
    )

    return flags
}

function spyOnFeatureFlags(featureFlags: FeatureFlagsSet): FeatureFlagsSet {
    const appContext = getAppContext()
    const persistedFlags = getPersistedFeatureFlags(appContext)
    const availableFlags =
        appContext?.preflight?.cloud || appContext?.preflight?.is_debug || process.env.NODE_ENV === 'test'
            ? { ...persistedFlags, ...featureFlags }
            : persistedFlags

    if (typeof window.Proxy !== 'undefined') {
        return new Proxy(
            {},
            {
                get(_, flag) {
                    if (flag === 'toJSON') {
                        return () => availableFlags
                    }
                    const flagString = flag.toString()
                    const flagState = availableFlags[flagString as FeatureFlagKey]
                    notifyFlagIfNeeded(flagString, flagState)
                    return flagState
                },
            }
        )
    }
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

export function getFeatureFlagPayload(flag: FeatureFlagKey): any {
    return posthog.getFeatureFlagPayload(flag)
}

export const featureFlagLogic = kea<featureFlagLogicType>([
    path(['lib', 'logic', 'featureFlagLogic']),
    actions({
        setFeatureFlags: (flags: string[], variants: Record<string, string | boolean>) => ({ flags, variants }),
    }),
    reducers({
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
    }),
    afterMount(({ actions }) => {
        posthog.onFeatureFlags(actions.setFeatureFlags)
    }),
])

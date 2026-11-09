import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

// pinned: posthog-js persistence key for local flag overrides
const FLAG_OVERRIDES_PROPERTY = '$override_feature_flags'

function currentFlagOverrides(): Record<string, string | boolean> {
    const overrides = posthog.get_property(FLAG_OVERRIDES_PROPERTY)
    return overrides && typeof overrides === 'object' && !Array.isArray(overrides) ? { ...overrides } : {}
}

/** True when this browser has switched the new design off, so the flag is on for this person underneath. */
export function hasTodayRailNavOptOut(): boolean {
    return currentFlagOverrides()[FEATURE_FLAGS.TODAY_RAIL_NAV] === false
}

/**
 * Switches the new design on or off for this browser only, by overriding the flag locally, then reloads.
 * Other flag overrides are kept. The whole shell is chosen at mount, so a reload is cleaner than swapping it live.
 */
export function setTodayRailNavEnabled(enabled: boolean): void {
    posthog.featureFlags.overrideFeatureFlags({
        flags: { ...currentFlagOverrides(), [FEATURE_FLAGS.TODAY_RAIL_NAV]: enabled },
        suppressWarning: true,
    })
    window.location.reload()
}

export interface PageFlagOverrides {
    /** False when the page has no posthog-js instance on `window.posthog`. */
    available: boolean
    overrides: Record<string, string | boolean>
}

interface PagePostHog {
    featureFlags?: {
        overrideFeatureFlags?: (overrides: { flags: Record<string, string | boolean> } | false) => void
    }
    get_property?: (key: string) => unknown
}

/**
 * Runs in the page's own JavaScript world through `scripting.executeScript`, because the content script's
 * isolated world can't reach the page's posthog-js instance. The browser serializes this function, so it
 * must not use imports or values from outside its body.
 *
 * Pass null to read the overrides without a change.
 */
export function applyPageFlagOverrides(flags: Record<string, string | boolean> | null): PageFlagOverrides {
    const posthog = (window as unknown as { posthog?: PagePostHog }).posthog
    const overrideFeatureFlags = posthog?.featureFlags?.overrideFeatureFlags
    if (!posthog || !overrideFeatureFlags || typeof posthog.get_property !== 'function') {
        return { available: false, overrides: {} }
    }
    if (flags) {
        overrideFeatureFlags.call(posthog.featureFlags, Object.keys(flags).length > 0 ? { flags } : false)
    }
    const overrides = posthog.get_property('$override_feature_flags')
    return {
        available: true,
        overrides: overrides && typeof overrides === 'object' ? (overrides as Record<string, string | boolean>) : {},
    }
}

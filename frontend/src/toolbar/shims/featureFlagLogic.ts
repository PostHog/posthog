import { kea, path, reducers } from 'kea'

// Toolbar shim — no feature flags available in toolbar context
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getFeatureFlagPayload(_flag: string): undefined {
    return undefined
}

export const featureFlagLogic = kea([
    path(['toolbar', 'shims', 'featureFlagLogic']),
    reducers({
        featureFlags: [{} as Record<string, string | boolean>, {}],
    }),
])

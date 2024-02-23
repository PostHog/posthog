export function apiHostOrigin(): string {
    let apiHost = window.location.origin
    // similar to https://github.com/PostHog/posthog-js/blob/b79315b7a4fa0caded7026bda2fec01defb0ba73/src/posthog-core.ts#L1742
    if (apiHost === 'https://us.posthog.com') {
        apiHost = 'https://us.i.posthog.com'
    }
    if (apiHost === 'https://eu.posthog.com') {
        apiHost = 'https://eu.i.posthog.com'
    }
    return apiHost
}
export function assetHostOrigin(): string {
    let assetHost = window.location.origin
    // similar to https://github.com/PostHog/posthog-js/blob/b79315b7a4fa0caded7026bda2fec01defb0ba73/src/posthog-core.ts#L1742
    if (assetHost === 'https://us.posthog.com') {
        assetHost = 'https://us-assets.i.posthog.com'
    }
    if (assetHost === 'https://eu.posthog.com') {
        assetHost = 'https://eu-assets.i.posthog.com'
    }
    return assetHost
}

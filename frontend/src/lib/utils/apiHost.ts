export function apiHostOrigin(): string {
    let apiHost = window.location.origin
    // similar to https://github.com/PostHog/posthog-js/blob/b79315b7a4fa0caded7026bda2fec01defb0ba73/src/posthog-core.ts#L1742
    if (apiHost === 'https://us.posthog.com') {
        apiHost = 'https://app.posthog.com'
    }
    return apiHost
}

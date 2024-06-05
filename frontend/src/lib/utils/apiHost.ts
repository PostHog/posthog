export function apiHostOrigin(): string {
    const appOrigin = window.location.origin
    if (appOrigin === 'https://us.posthog.com') {
        return 'https://us.i.posthog.com'
    } else if (appOrigin === 'https://eu.posthog.com') {
        return 'https://eu.i.posthog.com'
    }
    return appOrigin
}

export function liveEventsHostOrigin(): string | null {
    const appOrigin = window.location.origin
    if (appOrigin === 'https://us.posthog.com') {
        return 'https://live.us.posthog.com'
    } else if (appOrigin === 'https://eu.posthog.com') {
        return 'https://live.eu.posthog.com'
    }
    // TODO(@zach): add dev and local env support
    return null
}

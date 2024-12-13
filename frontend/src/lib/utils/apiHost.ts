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
    } else if (appOrigin === 'https://app.dev.posthog.dev') {
        return 'https://live.dev.posthog.dev'
    }
    return 'http://localhost:8666'
}

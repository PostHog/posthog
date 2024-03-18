export function apiHostOrigin(): string {
    let apiHost = window.location.origin

    if (apiHost === 'https://us.posthog.com') {
        apiHost = 'https://us.i.posthog.com'
    } else if (apiHost === 'https://eu.posthog.com') {
        apiHost = 'https://eu.i.posthog.com'
    }

    return apiHost
}

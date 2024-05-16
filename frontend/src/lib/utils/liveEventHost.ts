export function liveEventsHostOrigin(): string | undefined {
    let liveEventHost

    if (liveEventHost === 'https://us.posthog.com') {
        liveEventHost = 'https://live.us.posthog.com'
    } else if (liveEventHost === 'https://eu.posthog.com') {
        liveEventHost = 'https://live.eu.posthog.com'
    } else if (process.env.NODE_ENV === 'development') {
        // TODO(@zach): add dev and local env support
        liveEventHost = 'https://live.us.posthog.com'
    }

    return liveEventHost
}

import { getAppContext } from './getAppContext'

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
    const appContext = getAppContext()

    if (appOrigin === 'https://us.posthog.com') {
        return 'https://live.us.posthog.com'
    } else if (appOrigin === 'https://eu.posthog.com') {
        return 'https://live.eu.posthog.com'
    } else if (appOrigin === 'https://app.dev.posthog.dev') {
        return 'https://live.dev.posthog.dev'
    } else if (process.env.STORYBOOK) {
        return 'http://localhost:6006'
    }

    return appContext?.livestream_host || 'http://localhost:8666'
}

export function publicWebhooksHostOrigin(): string | null {
    const appOrigin = window.location.origin

    if (appOrigin === 'https://us.posthog.com') {
        return 'https://webhooks.us.posthog.com'
    } else if (appOrigin === 'https://eu.posthog.com') {
        return 'https://webhooks.eu.posthog.com'
    } else if (appOrigin === 'https://app.dev.posthog.dev') {
        return 'https://webhooks.dev.posthog.dev'
    }

    return appOrigin
}

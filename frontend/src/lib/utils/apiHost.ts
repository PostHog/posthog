import { getBackendHost } from 'lib/oauth/oauthClient'

import { inStorybook, inStorybookTestRunner } from './dom'
import { getAppContext } from './getAppContext'

/**
 * Resolve a backend-served asset path (e.g. `/uploaded_media/<id>`) to a full URL. These resources
 * live on the backend, not the SPA bundle's origin — so in OAuth mode, where the app runs against a
 * remote region, prefix that region's host. Same-origin (session) mode returns the path unchanged.
 * Already-absolute URLs and `data:` URIs pass through untouched.
 */
export function backendAssetUrl(path: string): string {
    if (/^(https?:|data:)/.test(path)) {
        return path
    }
    const backendHost = getBackendHost()
    return backendHost ? `${backendHost}${path}` : path
}

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
    } else if (inStorybook() || inStorybookTestRunner()) {
        return 'http://localhost:6006'
    }

    return appContext?.livestream_host || 'http://localhost:8666'
}

// Mirrors the dev port scheme in bin/worktree-stack (backend 8000 + 100i,
// proxy +10) — keep the three sites listed there in sync.
export function devProxyPortForBackendPort(port: number = Number(window.location.port)): number | null {
    return port >= 8000 && (port - 8000) % 100 === 0 ? port + 10 : null
}

export function publicWebhooksHostOrigin(): string | null {
    const appOrigin = window.location.origin

    if (appOrigin === 'https://us.posthog.com') {
        return 'https://webhooks.us.posthog.com'
    } else if (appOrigin === 'https://eu.posthog.com') {
        return 'https://webhooks.eu.posthog.com'
    } else if (appOrigin === 'https://app.dev.posthog.dev') {
        return 'https://app.dev.posthog.dev'
    }

    return appOrigin
}

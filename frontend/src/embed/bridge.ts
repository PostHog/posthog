/**
 * postMessage bridge between the embedded PostHog app and its host window.
 *
 * Protocol (all messages are plain objects with a `source` discriminator):
 *   host -> iframe  { source: 'posthog-embed-host', type: 'navigate', url }
 *   host -> iframe  { source: 'posthog-embed-host', type: 'setTheme', theme: 'light' | 'dark' | null }
 *   iframe -> host  { source: 'posthog-embed', type: 'ready', url }
 *   iframe -> host  { source: 'posthog-embed', type: 'routeChanged', url }
 *
 * Navigation goes through kea-router, which auto-prefixes `/project/<id>` —
 * the host should send bare paths like `/notebooks`.
 */
import { getContext } from 'kea'
import { router } from 'kea-router'

import { themeLogic } from 'lib/logic/themeLogic'

const FROM_EMBED = 'posthog-embed'
const FROM_HOST = 'posthog-embed-host'

function postToHost(message: Record<string, unknown>): void {
    window.parent.postMessage({ source: FROM_EMBED, ...message }, '*')
}

function currentUrl(): string {
    const { pathname, search, hash } = window.location
    return `${pathname}${search}${hash}`
}

function keaIsReady(): boolean {
    try {
        return !!getContext().store
    } catch {
        return false
    }
}

/** Called by the embed entry once the main app bundle has been imported. */
export function initEmbedBridge(): void {
    if (window.parent === window) {
        return // not framed: nothing to bridge
    }
    // The main entry lazy-loads the App chunk and only then runs initKea, so
    // poll until the kea context exists before touching logics or the router.
    const timer = window.setInterval(() => {
        if (keaIsReady()) {
            window.clearInterval(timer)
            start()
        }
    }, 50)
}

function start(): void {
    // Keep themeLogic mounted for the app's lifetime so the forced theme
    // doesn't unmount away with whatever scene mounted it first.
    themeLogic.mount()

    if (window.__POSTHOG_EMBED_THEME__) {
        themeLogic.actions.setEmbedForcedTheme(window.__POSTHOG_EMBED_THEME__)
    }

    window.addEventListener('message', (event: MessageEvent) => {
        const data: unknown = event.data
        if (!data || typeof data !== 'object' || (data as Record<string, unknown>).source !== FROM_HOST) {
            return
        }
        const message = data as { type?: string; url?: unknown; theme?: unknown }
        if (message.type === 'navigate' && typeof message.url === 'string') {
            router.actions.push(message.url)
        } else if (message.type === 'setTheme') {
            themeLogic.actions.setEmbedForcedTheme(
                message.theme === 'dark' ? 'dark' : message.theme === 'light' ? 'light' : null
            )
        }
    })

    let lastUrl = currentUrl()
    getContext().store.subscribe(() => {
        const url = currentUrl()
        if (url !== lastUrl) {
            lastUrl = url
            postToHost({ type: 'routeChanged', url })
        }
    })

    postToHost({ type: 'ready', url: lastUrl })
}

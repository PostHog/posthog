import {
    PAGE_AGENT_REPLY_SOURCE,
    PageAgentReply,
    PageAgentReplyMessage,
    isPageAgentRequestMessage,
} from './pageAgentProtocol'
import type { PageAnalyticsInfo } from './pageToolbarBridge'

interface PagePosthog {
    __loaded?: boolean
    version?: string
    config?: {
        disable_scroll_properties?: boolean
        scroll_root_selector?: string | string[]
    }
    heatmaps?: { isEnabled?: boolean }
}

// The panel injects this file again on each connection, so a second run in the same page must do nothing.
const INSTALLED_FLAG = '__posthogToolbarExtensionPageAgent'

// An async snippet loads posthog-js after the page loads, so the agent watches for it this often, for this long.
const POSTHOG_CHECK_INTERVAL_MS = 500
const POSTHOG_CHECK_DURATION_MS = 10_000

/** A page can replace any of these with a getter that throws, so each read stands alone. */
function read<T>(get: () => T | null | undefined, fallback: T): T {
    try {
        return get() ?? fallback
    } catch {
        return fallback
    }
}

/** The snippet's stub array has none of posthog-js's methods until the library loads. */
function pagePosthog(): PagePosthog | null {
    const posthog = (window as unknown as { posthog?: PagePosthog }).posthog
    return posthog && typeof posthog === 'object' && (posthog.__loaded || typeof posthog.version === 'string')
        ? posthog
        : null
}

function analyticsInfo(posthog: PagePosthog): PageAnalyticsInfo {
    return {
        version: read(() => posthog.version, null),
        scrollPropertiesDisabled: !!read(() => posthog.config?.disable_scroll_properties, false),
        scrollRootSelector: read(() => posthog.config?.scroll_root_selector, null),
        heatmapsEnabled: posthog.heatmaps ? !!read(() => posthog.heatmaps?.isEnabled, false) : null,
    }
}

function reply(message: PageAgentReply): void {
    window.postMessage(
        { source: PAGE_AGENT_REPLY_SOURCE, reply: message } satisfies PageAgentReplyMessage,
        window.location.origin
    )
}

function install(): void {
    window.addEventListener('message', (event) => {
        if (event.source !== window || !isPageAgentRequestMessage(event.data)) {
            return
        }
        const posthog = pagePosthog()
        reply({ kind: 'analytics', id: event.data.id, info: posthog ? analyticsInfo(posthog) : null })
    })

    if (pagePosthog()) {
        return
    }
    const startedAt = Date.now()
    const interval = setInterval(() => {
        const loaded = pagePosthog()
        if (loaded) {
            reply({ kind: 'analytics', id: null, info: analyticsInfo(loaded) })
        }
        if (loaded || Date.now() - startedAt > POSTHOG_CHECK_DURATION_MS) {
            clearInterval(interval)
        }
    }, POSTHOG_CHECK_INTERVAL_MS)
}

const pageGlobal = window as unknown as Record<string, boolean | undefined>
if (!pageGlobal[INSTALLED_FLAG]) {
    pageGlobal[INSTALLED_FLAG] = true
    install()
}

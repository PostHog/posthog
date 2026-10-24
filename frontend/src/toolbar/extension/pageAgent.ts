import {
    PAGE_AGENT_REPLY_SOURCE,
    PageAgentReply,
    PageAgentReplyMessage,
    PageAgentRequest,
    isPageAgentRequestMessage,
} from './pageAgentProtocol'
import type { PageAnalyticsInfo, PageFeatureFlagsSnapshot } from './pageToolbarBridge'

interface PagePosthog {
    __loaded?: boolean
    version?: string
    config?: {
        disable_scroll_properties?: boolean
        scroll_root_selector?: string | string[]
    }
    heatmaps?: { isEnabled?: boolean }
    featureFlags?: {
        overrideFeatureFlags?: (overrides: unknown) => void
        reloadFeatureFlags?: () => void
        getFlagVariants?: () => Record<string, string | boolean>
    }
    get_property?: (key: string) => unknown
    getGroups?: () => Record<string, string>
    onFeatureFlags?: (callback: () => void) => unknown
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

function featureFlagsSnapshot(posthog: PagePosthog): PageFeatureFlagsSnapshot {
    return {
        overrides: read(
            () => posthog.get_property?.('$override_feature_flags') as Record<string, string | boolean>,
            {}
        ),
        variants: read(() => posthog.featureFlags?.getFlagVariants?.(), {}),
        groups: read(() => posthog.getGroups?.(), {}),
    }
}

function analyticsInfo(posthog: PagePosthog): PageAnalyticsInfo {
    return {
        version: read(() => posthog.version, null),
        scrollPropertiesDisabled: !!read(() => posthog.config?.disable_scroll_properties, false),
        scrollRootSelector: read(() => posthog.config?.scroll_root_selector, null),
        heatmapsEnabled: posthog.heatmaps ? !!read(() => posthog.heatmaps?.isEnabled, false) : null,
        featureFlags: featureFlagsSnapshot(posthog),
    }
}

function reply(message: PageAgentReply): void {
    window.postMessage(
        { source: PAGE_AGENT_REPLY_SOURCE, reply: message } satisfies PageAgentReplyMessage,
        window.location.origin
    )
}

function install(): void {
    let flagsSubscribed = false

    const subscribeToFlags = (posthog: PagePosthog): void => {
        if (!flagsSubscribed && posthog.onFeatureFlags) {
            flagsSubscribed = true
            posthog.onFeatureFlags(() => reply({ kind: 'feature-flags', featureFlags: featureFlagsSnapshot(posthog) }))
        }
    }

    const run = (posthog: PagePosthog, id: number, request: PageAgentRequest): void => {
        switch (request.method) {
            case 'read-analytics':
                reply({ kind: 'analytics', id, info: analyticsInfo(posthog) })
                return
            case 'override-flags':
            case 'reload-flags':
                try {
                    subscribeToFlags(posthog)
                    if (request.method === 'override-flags') {
                        posthog.featureFlags?.overrideFeatureFlags?.(
                            request.flags === false ? false : { flags: request.flags, payloads: request.payloads }
                        )
                    } else {
                        posthog.featureFlags?.reloadFeatureFlags?.()
                    }
                    reply({ kind: 'result', id, ok: true, featureFlags: featureFlagsSnapshot(posthog) })
                } catch (error) {
                    reply({
                        kind: 'result',
                        id,
                        ok: false,
                        error: error instanceof Error ? error.message : String(error),
                    })
                }
                return
        }
    }

    window.addEventListener('message', (event) => {
        if (event.source !== window || !isPageAgentRequestMessage(event.data)) {
            return
        }
        const { id, request } = event.data
        const posthog = pagePosthog()
        if (posthog) {
            run(posthog, id, request)
        } else if (request.method === 'read-analytics') {
            reply({ kind: 'analytics', id, info: null })
        } else {
            reply({ kind: 'result', id, ok: false, error: 'The page has no posthog-js' })
        }
    })

    const posthog = pagePosthog()
    if (posthog) {
        subscribeToFlags(posthog)
        return
    }
    const startedAt = Date.now()
    const interval = setInterval(() => {
        const loaded = pagePosthog()
        if (loaded) {
            subscribeToFlags(loaded)
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

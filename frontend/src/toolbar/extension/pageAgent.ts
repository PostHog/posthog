import { DebugInfoPosthog, readPosthogDebugInfo } from '~/toolbar/shared/debug/posthogDebugInfo'

import {
    PAGE_AGENT_REPLY_SOURCE,
    PageAgentReply,
    PageAgentReplyMessage,
    PageAgentRequest,
    isPageAgentRequestMessage,
} from './messaging/pageAgentProtocol'
import type { PageAnalyticsInfo, PageDebugInfo, PageFeatureFlagsSnapshot } from './messaging/pageToolbarBridge'

interface PagePosthog extends DebugInfoPosthog {
    __loaded?: boolean
    config?: DebugInfoPosthog['config'] & {
        disable_scroll_properties?: boolean
        disable_web_experiments?: boolean
        scroll_root_selector?: string | string[]
        session_recording?: Record<string, unknown>
    }
    webVitalsAutocapture?: { isEnabled?: boolean }
    featureFlags?: {
        overrideFeatureFlags?: (overrides: unknown) => void
        reloadFeatureFlags?: () => void
        getFlagVariants?: () => Record<string, string | boolean>
    }
    get_property?: (key: string) => unknown
    getGroups?: () => Record<string, string>
    onFeatureFlags?: (callback: () => void) => unknown
    on?: (event: 'eventCaptured', callback: (event: unknown) => void) => unknown
    surveys?: { getSurveys?: (callback: (surveys: unknown[]) => void, forceReload?: boolean) => void }
}

// The panel injects this file again on each connection, so a second run in the same page must do nothing.
const INSTALLED_FLAG = '__posthogToolbarExtensionPageAgent'

const SURVEYS_TIMEOUT_MS = 2000

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
    const sessionRecording = posthog.config?.session_recording ?? {}
    return {
        version: read(() => posthog.version, null),
        scrollPropertiesDisabled: !!read(() => posthog.config?.disable_scroll_properties, false),
        scrollRootSelector: read(() => posthog.config?.scroll_root_selector, null),
        heatmapsEnabled: posthog.heatmaps ? !!read(() => posthog.heatmaps?.isEnabled, false) : null,
        webVitalsEnabled: posthog.webVitalsAutocapture
            ? !!read(() => posthog.webVitalsAutocapture?.isEnabled, false)
            : null,
        webExperimentsDisabled: !!read(() => posthog.config?.disable_web_experiments, false),
        sessionRecordingConfig: Object.fromEntries(
            ['blockClass', 'maskTextClass', 'maskTextSelector', 'maskAllInputs']
                .map((key): [string, unknown] => [key, sessionRecording[key]])
                .filter(([, value]) => value !== undefined)
                // A RegExp or a function can't leave the page, and the masking preview treats any non-string the same.
                .map(([key, value]) => [key, ['string', 'boolean'].includes(typeof value) ? value : {}])
        ),
        sessionRecordingStatus: read(() => posthog.sessionRecording?.status, null),
        featureFlags: featureFlagsSnapshot(posthog),
    }
}

function reply(message: PageAgentReply): void {
    window.postMessage(
        { source: PAGE_AGENT_REPLY_SOURCE, reply: message } satisfies PageAgentReplyMessage,
        window.location.origin
    )
}

function postCapturedEvent(event: unknown, forwardSnapshotPayloads: boolean): void {
    // A snapshot carries the page's recording, which a debugger that hides snapshots never shows.
    const forwarded =
        !forwardSnapshotPayloads && (event as { event?: string } | null)?.event === '$snapshot'
            ? { ...(event as Record<string, unknown>), properties: {} }
            : event
    try {
        reply({ kind: 'event-captured', event: forwarded })
    } catch {
        // postMessage can't clone a function or a DOM node, which some event properties can hold.
        try {
            reply({ kind: 'event-captured', event: JSON.parse(JSON.stringify(forwarded)) })
        } catch {
            // An event that JSON can't hold either never reaches the debugger.
        }
    }
}

function readDebugInfo(posthog: PagePosthog): Promise<PageDebugInfo> {
    const info = readPosthogDebugInfo(posthog)
    return new Promise((resolve) => {
        const finish = (surveysCount: number | null): void => resolve({ ...info, surveysCount })
        const getSurveys = posthog.surveys?.getSurveys
        if (!getSurveys) {
            finish(null)
            return
        }
        const timeout = setTimeout(() => finish(null), SURVEYS_TIMEOUT_MS)
        try {
            getSurveys.call(
                posthog.surveys,
                (surveys) => {
                    clearTimeout(timeout)
                    finish(Array.isArray(surveys) ? surveys.length : null)
                },
                false
            )
        } catch {
            clearTimeout(timeout)
            finish(null)
        }
    })
}

function install(): void {
    let flagsSubscribed = false
    let forwardSnapshotPayloads = false
    let unsubscribeEvents: (() => void) | null = null

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
            case 'subscribe-events': {
                forwardSnapshotPayloads = request.forwardSnapshotPayloads
                if (!unsubscribeEvents && posthog.on) {
                    const unsubscribe = posthog.on('eventCaptured', (event) =>
                        postCapturedEvent(event, forwardSnapshotPayloads)
                    )
                    unsubscribeEvents = typeof unsubscribe === 'function' ? (unsubscribe as () => void) : () => {}
                }
                return
            }
            case 'unsubscribe-events':
                unsubscribeEvents?.()
                unsubscribeEvents = null
                return
            case 'read-debug-info':
                void readDebugInfo(posthog).then((info) => reply({ kind: 'debug-info', id, info }))
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

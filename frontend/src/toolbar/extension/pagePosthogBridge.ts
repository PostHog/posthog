import type { PostHog } from 'posthog-js'

import {
    PAGE_AGENT_REQUEST_SOURCE,
    PageAgentReply,
    PageAgentRequest,
    PageAgentRequestMessage,
    isPageAgentReplyMessage,
} from './pageAgentProtocol'
import type { PageAnalyticsInfo } from './pageToolbarBridge'

// The page agent answers in milliseconds. Past this, the page most likely reloaded or has no agent.
const ANALYTICS_TIMEOUT_MS = 1000

let nextRequestId = 1

function postToPageAgent(request: PageAgentRequest): number {
    const id = nextRequestId++
    window.postMessage({ source: PAGE_AGENT_REQUEST_SOURCE, id, request } satisfies PageAgentRequestMessage, '*')
    return id
}

function onPageAgentReply(handler: (reply: PageAgentReply) => void): () => void {
    const listener = (event: MessageEvent): void => {
        if (event.source === window && isPageAgentReplyMessage(event.data)) {
            handler(event.data.reply)
        }
    }
    window.addEventListener('message', listener)
    return () => window.removeEventListener('message', listener)
}

/** Resolves with null when the page has no posthog-js. */
export function requestPageAnalytics(): Promise<PageAnalyticsInfo | null> {
    return new Promise((resolve) => {
        const id = postToPageAgent({ method: 'read-analytics' })
        const finish = (info: PageAnalyticsInfo | null): void => {
            clearTimeout(timeout)
            removeListener()
            resolve(info)
        }
        const timeout = setTimeout(() => finish(null), ANALYTICS_TIMEOUT_MS)
        const removeListener = onPageAgentReply((reply) => {
            if (reply.kind === 'analytics' && reply.id === id) {
                finish(reply.info)
            }
        })
    })
}

/** The page agent reports by itself when a page's posthog-js loads after the page tools started. */
export function onPagePosthogAppeared(handler: () => void): void {
    onPageAgentReply((reply) => {
        if (reply.kind === 'analytics' && reply.id === null && reply.info) {
            handler()
        }
    })
}

/** Stands in for the page's posthog-js in the content script, with the settings the page agent read from it. */
export class PagePosthogBridge {
    /** The parts of posthog-js that the toolbar's logics read. */
    readonly posthog: PostHog

    constructor(info: PageAnalyticsInfo) {
        this.posthog = {
            version: info.version ?? undefined,
            config: {
                disable_scroll_properties: info.scrollPropertiesDisabled,
                scroll_root_selector: info.scrollRootSelector ?? undefined,
            },
            heatmaps: info.heatmapsEnabled === null ? undefined : { isEnabled: info.heatmapsEnabled },
            // Matches posthog-js, which measures scroll depth on the page's scroll root when the config names one.
            scrollManager: { scrollY: () => scrollRoot(info.scrollRootSelector)?.scrollTop ?? window.scrollY },
        } as unknown as PostHog
    }
}

function scrollRoot(selector: string | string[] | null): Element | null {
    for (const candidate of Array.isArray(selector) ? selector : selector ? [selector] : []) {
        try {
            const element = document.querySelector(candidate)
            if (element) {
                return element
            }
        } catch {
            // The page's config names an invalid selector, which posthog-js skips too.
        }
    }
    return null
}

import type { PageAnalyticsInfo, PageDebugInfo, PageFeatureFlagsSnapshot } from './pageToolbarBridge'

// The content script's isolated world can't call the page's `window.posthog`, so the page agent calls it from the
// page's own world.

// pinned: page message sources, the page agent and an already injected content script must agree on them
export const PAGE_AGENT_REQUEST_SOURCE = 'posthog-toolbar-extension-request'
export const PAGE_AGENT_REPLY_SOURCE = 'posthog-toolbar-extension-reply'

export type PageAgentRequest =
    | { method: 'read-analytics' }
    | { method: 'override-flags'; flags: Record<string, string | boolean> | false; payloads?: Record<string, unknown> }
    | { method: 'reload-flags' }
    | { method: 'subscribe-events'; forwardSnapshotPayloads: boolean }
    | { method: 'unsubscribe-events' }
    | { method: 'read-debug-info' }

export type PageAgentReply =
    /** `id` is null when the page agent reports by itself that posthog-js appeared on the page. */
    | { kind: 'analytics'; id: number | null; info: PageAnalyticsInfo | null }
    | { kind: 'result'; id: number; ok: true; featureFlags: PageFeatureFlagsSnapshot }
    | { kind: 'result'; id: number; ok: false; error: string }
    | { kind: 'feature-flags'; featureFlags: PageFeatureFlagsSnapshot }
    | { kind: 'event-captured'; event: unknown }
    | { kind: 'debug-info'; id: number; info: PageDebugInfo }

export interface PageAgentRequestMessage {
    source: typeof PAGE_AGENT_REQUEST_SOURCE
    id: number
    request: PageAgentRequest
}

export interface PageAgentReplyMessage {
    source: typeof PAGE_AGENT_REPLY_SOURCE
    reply: PageAgentReply
}

export function isPageAgentRequestMessage(data: unknown): data is PageAgentRequestMessage {
    return (
        !!data &&
        typeof data === 'object' &&
        (data as Partial<PageAgentRequestMessage>).source === PAGE_AGENT_REQUEST_SOURCE &&
        typeof (data as Partial<PageAgentRequestMessage>).id === 'number'
    )
}

export function isPageAgentReplyMessage(data: unknown): data is PageAgentReplyMessage {
    return (
        !!data &&
        typeof data === 'object' &&
        (data as Partial<PageAgentReplyMessage>).source === PAGE_AGENT_REPLY_SOURCE &&
        !!(data as Partial<PageAgentReplyMessage>).reply
    )
}

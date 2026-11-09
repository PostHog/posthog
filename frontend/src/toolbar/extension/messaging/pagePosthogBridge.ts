import type { PostHog } from 'posthog-js'

import {
    PAGE_AGENT_REQUEST_SOURCE,
    PageAgentReply,
    PageAgentRequest,
    PageAgentRequestMessage,
    isPageAgentReplyMessage,
} from './pageAgentProtocol'
import type { PageAnalyticsInfo, PageDebugInfo, PageFeatureFlagsSnapshot } from './pageToolbarBridge'

export interface PageFlagMutationStatus {
    pending: boolean
    error: string | null
    revision: number
}

type FeatureFlagsCallback = (flags: string[], variants: Record<string, string | boolean>) => void

type EventCapturedCallback = (event: unknown) => void

// The page agent answers in milliseconds. Past these, the page most likely reloaded or has no agent.
const ANALYTICS_TIMEOUT_MS = 1000
const MUTATION_TIMEOUT_MS = 5000
const DEBUG_INFO_TIMEOUT_MS = 5000

let nextRequestId = 1

function postToPageAgent(request: PageAgentRequest): number {
    const id = nextRequestId++
    window.postMessage(
        { source: PAGE_AGENT_REQUEST_SOURCE, id, request } satisfies PageAgentRequestMessage,
        window.location.origin
    )
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

/**
 * Stands in for the page's posthog-js in the content script. The toolbar's logics read posthog-js synchronously, so
 * this keeps a copy of the page's flag state and updates it as soon as it sends a change, before the page agent answers.
 */
export class PagePosthogBridge {
    private featureFlags: PageFeatureFlagsSnapshot
    private pendingMutations = new Map<number, ReturnType<typeof setTimeout>>()
    private featureFlagsCallbacks: FeatureFlagsCallback[] = []
    private eventCapturedCallbacks: EventCapturedCallback[] = []
    private forwardSnapshotPayloads = false
    private debugInfoRequests = new Map<number, (info: PageDebugInfo | null) => void>()
    private mutationStatus: PageFlagMutationStatus = { pending: false, error: null, revision: 0 }
    private removeListener: () => void
    /** The parts of posthog-js that the toolbar's logics read. */
    readonly posthog: PostHog

    constructor(
        private readonly info: PageAnalyticsInfo,
        private readonly onChange: (status: PageFlagMutationStatus) => void
    ) {
        this.featureFlags = info.featureFlags
        this.removeListener = onPageAgentReply((reply) => this.handleReply(reply))
        this.posthog = this.buildPosthog()
    }

    dispose(): void {
        this.removeListener()
        if (this.eventCapturedCallbacks.length > 0) {
            postToPageAgent({ method: 'unsubscribe-events' })
        }
        for (const timeout of this.pendingMutations.values()) {
            clearTimeout(timeout)
        }
        this.pendingMutations.clear()
        for (const resolve of this.debugInfoRequests.values()) {
            resolve(null)
        }
        this.debugInfoRequests.clear()
    }

    /** Resolves with null when the page has no posthog-js, or when it doesn't answer in time. */
    readDebugInfo(): Promise<PageDebugInfo | null> {
        const id = postToPageAgent({ method: 'read-debug-info' })
        return new Promise((resolve) => {
            const timeout = setTimeout(() => this.resolveDebugInfo(id, null), DEBUG_INFO_TIMEOUT_MS)
            this.debugInfoRequests.set(id, (info) => {
                clearTimeout(timeout)
                resolve(info)
            })
        })
    }

    setForwardSnapshotPayloads(forward: boolean): void {
        this.forwardSnapshotPayloads = forward
        if (this.eventCapturedCallbacks.length > 0) {
            postToPageAgent({ method: 'subscribe-events', forwardSnapshotPayloads: forward })
        }
    }

    private buildPosthog(): PostHog {
        const { info } = this
        return {
            version: info.version ?? undefined,
            config: {
                disable_scroll_properties: info.scrollPropertiesDisabled,
                disable_web_experiments: info.webExperimentsDisabled,
                scroll_root_selector: info.scrollRootSelector ?? undefined,
                session_recording: info.sessionRecordingConfig,
            },
            heatmaps: info.heatmapsEnabled === null ? undefined : { isEnabled: info.heatmapsEnabled },
            webVitalsAutocapture: info.webVitalsEnabled === null ? undefined : { isEnabled: info.webVitalsEnabled },
            sessionRecording: { status: info.sessionRecordingStatus ?? undefined },
            on: (event: string, callback: EventCapturedCallback) => {
                if (event !== 'eventCaptured') {
                    return () => {}
                }
                if (this.eventCapturedCallbacks.length === 0) {
                    postToPageAgent({
                        method: 'subscribe-events',
                        forwardSnapshotPayloads: this.forwardSnapshotPayloads,
                    })
                }
                this.eventCapturedCallbacks.push(callback)
                return () => {
                    this.eventCapturedCallbacks = this.eventCapturedCallbacks.filter((c) => c !== callback)
                    if (this.eventCapturedCallbacks.length === 0) {
                        postToPageAgent({ method: 'unsubscribe-events' })
                    }
                }
            },
            // Matches posthog-js, which measures scroll depth on the page's scroll root when the config names one.
            scrollManager: { scrollY: () => scrollRoot(info.scrollRootSelector)?.scrollTop ?? window.scrollY },
            featureFlags: {
                overrideFeatureFlags: (
                    overrides: { flags?: Record<string, string | boolean>; payloads?: Record<string, unknown> } | false
                ) => this.overrideFeatureFlags(overrides),
                reloadFeatureFlags: () => this.sendMutation({ method: 'reload-flags' }),
                getFlagVariants: () => this.featureFlags.variants,
            },
            get_property: (key: string) =>
                key === '$override_feature_flags' ? this.featureFlags.overrides : undefined,
            getGroups: () => this.featureFlags.groups,
            onFeatureFlags: (callback: FeatureFlagsCallback) => {
                this.featureFlagsCallbacks.push(callback)
                return () => {
                    this.featureFlagsCallbacks = this.featureFlagsCallbacks.filter((c) => c !== callback)
                }
            },
        } as unknown as PostHog
    }

    private overrideFeatureFlags(
        overrides: { flags?: Record<string, string | boolean>; payloads?: Record<string, unknown> } | false
    ): void {
        const flags = overrides === false ? false : (overrides.flags ?? {})
        this.featureFlags = { ...this.featureFlags, overrides: flags === false ? {} : flags }
        this.sendMutation(
            overrides === false
                ? { method: 'override-flags', flags: false }
                : { method: 'override-flags', flags: overrides.flags ?? {}, payloads: overrides.payloads }
        )
    }

    /** A flag change shows as pending until the page agent answers, or fails when it doesn't answer in time. */
    private sendMutation(request: PageAgentRequest): void {
        const id = postToPageAgent(request)
        this.pendingMutations.set(
            id,
            setTimeout(() => this.finishMutation(id, "The page didn't answer."), MUTATION_TIMEOUT_MS)
        )
        this.setMutationStatus({ pending: true })
    }

    private finishMutation(id: number, error: string | null): void {
        const timeout = this.pendingMutations.get(id)
        if (timeout === undefined) {
            return
        }
        clearTimeout(timeout)
        this.pendingMutations.delete(id)
        this.setMutationStatus({
            pending: this.pendingMutations.size > 0,
            error,
            revision: this.mutationStatus.revision + 1,
        })
    }

    private resolveDebugInfo(id: number, info: PageDebugInfo | null): void {
        const resolve = this.debugInfoRequests.get(id)
        this.debugInfoRequests.delete(id)
        resolve?.(info)
    }

    private handleReply(reply: PageAgentReply): void {
        if (reply.kind === 'event-captured') {
            for (const callback of this.eventCapturedCallbacks) {
                callback(reply.event)
            }
            return
        }
        if (reply.kind === 'debug-info') {
            this.resolveDebugInfo(reply.id, reply.info)
            return
        }
        if (reply.kind === 'feature-flags') {
            this.setFeatureFlags(reply.featureFlags)
            this.onChange(this.mutationStatus)
            return
        }
        if (reply.kind !== 'result') {
            return
        }
        if (this.debugInfoRequests.has(reply.id)) {
            // The page agent answers with a failed result when the page has no posthog-js.
            this.resolveDebugInfo(reply.id, null)
            return
        }
        if (!this.pendingMutations.has(reply.id)) {
            return
        }
        if (reply.ok) {
            this.setFeatureFlags(reply.featureFlags)
        }
        this.finishMutation(reply.id, reply.ok ? null : reply.error)
    }

    private setFeatureFlags(featureFlags: PageFeatureFlagsSnapshot): void {
        this.featureFlags = featureFlags
        for (const callback of this.featureFlagsCallbacks) {
            callback(Object.keys(featureFlags.variants), featureFlags.variants)
        }
    }

    private setMutationStatus(patch: Partial<PageFlagMutationStatus>): void {
        this.mutationStatus = { ...this.mutationStatus, ...patch }
        this.onChange(this.mutationStatus)
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

// React DOM's deletion/insertion reconciler throws these when the live DOM is rewritten out
// from under React — almost always a browser translation or ad-block extension mutating the
// page (the classic React issue #11538 `removeChild` crash). We recognise them in two places:
// `ErrorBoundary` shows a "caused by a browser extension" hint instead of a broken screen, and
// the error-tracking `before_send` filter collapses them onto one stable fingerprint so the
// hash-rotated JS-chunk variants stop spawning a fresh issue on every deploy.
export const DOM_MUTATION_PATTERNS = [
    "Failed to execute 'removeChild' on 'Node'",
    "Failed to execute 'insertBefore' on 'Node'",
    "Failed to execute 'appendChild' on 'Node'",
]

export function messageIsDOMMutationError(message: string | null | undefined): boolean {
    return !!message && DOM_MUTATION_PATTERNS.some((pattern) => message.includes(pattern))
}

export function isDOMModificationError(error: Error): boolean {
    return messageIsDOMMutationError(error.message)
}

// Every hash-rotated chunk variant of the browser-extension DOM crash shares this fingerprint,
// so error tracking groups them into a single issue the team can triage or mute once, rather
// than filing a new "first observed" issue each time a chunk hash changes on deploy.
export const DOM_MUTATION_EXCEPTION_FINGERPRINT = 'browser-extension-dom-mutation'

// A posthog-js `before_send` filter: stamps a stable `$exception_fingerprint` on `$exception`
// events whose chain carries a DOM-mutation error. Generic over the event shape so it can be
// unit-tested with plain object literals while staying assignable to `BeforeSendFn`.
export function fingerprintDOMMutationExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T {
    if (!event || event.event !== '$exception' || !event.properties) {
        return event
    }
    // Respect a fingerprint the client or a grouping rule already set.
    if (event.properties.$exception_fingerprint) {
        return event
    }
    const list = (event.properties.$exception_list ?? []) as Array<{ value?: string }>
    if (list.some((ex) => messageIsDOMMutationError(ex?.value))) {
        event.properties.$exception_fingerprint = DOM_MUTATION_EXCEPTION_FINGERPRINT
    }
    return event
}

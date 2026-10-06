import {
    CANVAS_CHANNEL,
    CanvasNavIntent,
    CanvasRect,
    CanvasTextSelection,
    CanvasToHostMessage,
    HostToCanvasMessage,
    isSafeGitHubPullRequestUrl,
    isSafePostHogUrl,
} from './canvasProtocol'

// Canvas code can post open-external without a gesture, so opens are limited.
export const EXTERNAL_OPEN_MIN_INTERVAL_MS = 1_000
// Canvas code is untrusted, so a runaway loop must not pile up concurrent requests,
// ship oversized payloads, or hold a request slot forever.
export const MAX_CONCURRENT_DATA_REQUESTS = 8
export const MAX_CONCURRENT_CONNECTOR_REQUESTS = 8
export const MAX_DATA_REQUEST_BYTES = 64 * 1024
export const DATA_REQUEST_TIMEOUT_MS = 30_000

const REPLAYABLE_SHORTCUT_KEYS = new Set([
    ',',
    '/',
    '[',
    ']',
    '{',
    '}',
    '1',
    '2',
    '3',
    '4',
    '5',
    '6',
    '7',
    '8',
    '9',
    'arrowdown',
    'arrowleft',
    'arrowright',
    'arrowup',
    'b',
    'i',
    'j',
    'k',
    'n',
    't',
    'tab',
])

// These write or start work, so the canvas must not fire them just by loading.
const GESTURE_GATED_METHODS = new Set(['actionInvoke', 'agentRequest'])
const GESTURE_GATED_NAV_TARGETS = new Set<CanvasNavIntent['target']>(['connect', 'compose-task', 'new-task'])
// Approval dialogs can stay open longer than the I/O timeout, so these wait unbounded.
const UNTIMED_METHODS = new Set(['agentRequest', 'actionInvoke', 'connectorCall'])

function isBoundedPayload(payload: unknown): boolean {
    try {
        return (JSON.stringify(payload) ?? '').length <= MAX_DATA_REQUEST_BYTES
    } catch {
        return false
    }
}

export interface CanvasHostCallbacks {
    onDataRequest: (method: string, payload: unknown) => Promise<unknown>
    onError?: (message: string, stack?: string) => void
    onReady?: () => void
    onRendered?: () => void
    onNavigate?: (intent: CanvasNavIntent) => void
    /** The viewer selected text in the canvas. The rect is in the frame's coordinates. */
    onTextSelection?: (selection: CanvasTextSelection) => void
    onTextSelectionCleared?: () => void
    /** The viewer clicked a highlighted comment anchor. */
    onCommentActivate?: (id: string, rect: CanvasRect | null) => void
}

export type ExternalOpenBlockReason = 'unsafe-url' | 'no-interaction' | 'throttled'

export interface CanvasHostMessageRouterOptions {
    /** Transport back into the canvas through its document port. */
    post: (message: HostToCanvasMessage) => void
    /** Read fresh per message, so the router can live for the whole mount without going stale. */
    callbacks: () => CanvasHostCallbacks
    /** Whether the browser is processing a trusted user gesture right now. */
    hasUserActivation: () => boolean
    /** Runs once the safety, gesture and throttle gates pass. */
    openExternal: (url: string) => void
    onExternalOpenBlocked?: (url: string, reason: ExternalOpenBlockReason) => void
    now?: () => number
}

/** The host side of the canvas protocol, shared by the built and the draft iframe. */
export function createCanvasHostMessageRouter(
    options: CanvasHostMessageRouterOptions
): (message: CanvasToHostMessage) => Promise<void> {
    const now = options.now ?? Date.now
    let lastExternalOpen = Number.NEGATIVE_INFINITY
    let activeDataRequests = 0
    let activeConnectorRequests = 0

    const respondError = (id: string, error: string): void =>
        options.post({ channel: CANVAS_CHANNEL, type: 'data-response', id, ok: false, error })

    return async (message) => {
        switch (message.type) {
            case 'data-request': {
                if (GESTURE_GATED_METHODS.has(message.method) && !options.hasUserActivation()) {
                    respondError(
                        message.id,
                        message.method === 'agentRequest'
                            ? 'Agent requests require a user action'
                            : 'Canvas actions require a user action'
                    )
                    break
                }
                // Approval waits must not consume ordinary read and write slots.
                const isConnectorRequest = message.method === 'connectorCall'
                const holdsSlot = message.method !== 'agentRequest' && !isConnectorRequest
                if (
                    (holdsSlot && activeDataRequests >= MAX_CONCURRENT_DATA_REQUESTS) ||
                    (isConnectorRequest && activeConnectorRequests >= MAX_CONCURRENT_CONNECTOR_REQUESTS) ||
                    !isBoundedPayload(message.payload)
                ) {
                    respondError(message.id, 'Canvas data request exceeds runtime limits')
                    break
                }
                if (holdsSlot) {
                    activeDataRequests += 1
                }
                if (isConnectorRequest) {
                    activeConnectorRequests += 1
                }
                let timer: ReturnType<typeof setTimeout> | undefined
                try {
                    const call = options.callbacks().onDataRequest(message.method, message.payload)
                    const result = UNTIMED_METHODS.has(message.method)
                        ? await call
                        : await Promise.race([
                              call,
                              new Promise<never>((_, reject) => {
                                  timer = setTimeout(
                                      () => reject(new Error('Canvas data request timed out')),
                                      DATA_REQUEST_TIMEOUT_MS
                                  )
                              }),
                          ])
                    options.post({ channel: CANVAS_CHANNEL, type: 'data-response', id: message.id, ok: true, result })
                } catch (error) {
                    respondError(message.id, error instanceof Error ? error.message : String(error))
                } finally {
                    clearTimeout(timer)
                    if (holdsSlot) {
                        activeDataRequests -= 1
                    }
                    if (isConnectorRequest) {
                        activeConnectorRequests -= 1
                    }
                }
                break
            }
            case 'error':
                options.callbacks().onError?.(message.message, message.stack)
                break
            case 'rendered':
                options.callbacks().onRendered?.()
                break
            case 'ready':
                options.callbacks().onReady?.()
                break
            case 'navigate':
                if (GESTURE_GATED_NAV_TARGETS.has(message.nav.target) && !options.hasUserActivation()) {
                    break
                }
                options.callbacks().onNavigate?.(message.nav)
                break
            case 'open-external':
                // Re-checks the schema's allowlist in case the two ever drift.
                if (!isSafePostHogUrl(message.url) && !isSafeGitHubPullRequestUrl(message.url)) {
                    options.onExternalOpenBlocked?.(message.url, 'unsafe-url')
                } else if (!options.hasUserActivation()) {
                    options.onExternalOpenBlocked?.(message.url, 'no-interaction')
                } else if (now() - lastExternalOpen < EXTERNAL_OPEN_MIN_INTERVAL_MS) {
                    options.onExternalOpenBlocked?.(message.url, 'throttled')
                } else {
                    lastExternalOpen = now()
                    options.openExternal(message.url)
                }
                break
            case 'keydown': {
                // Replays app shortcuts pressed while the iframe has focus.
                if (!message.metaKey && !message.ctrlKey) {
                    break
                }
                if (!REPLAYABLE_SHORTCUT_KEYS.has(message.key.toLowerCase())) {
                    break
                }
                if (!(document.activeElement instanceof HTMLIFrameElement)) {
                    break
                }
                const init = {
                    key: message.key,
                    code: message.code,
                    metaKey: message.metaKey,
                    ctrlKey: message.ctrlKey,
                    shiftKey: message.shiftKey,
                    altKey: message.altKey,
                }
                document.dispatchEvent(new KeyboardEvent('keydown', init))
                document.dispatchEvent(new KeyboardEvent('keyup', init))
                break
            }
            case 'text-selection':
                options.callbacks().onTextSelection?.(message.selection)
                break
            case 'text-selection-cleared':
                options.callbacks().onTextSelectionCleared?.()
                break
            case 'comment-activate':
                options.callbacks().onCommentActivate?.(message.id, message.rect ?? null)
                break
        }
    }
}

/**
 * Typed client for agent-ingress's chat trigger.
 *
 * Browser hits same-origin `/api/agents/v1/agents/<slug>/...` which
 * the Next.js catch-all proxy forwards to `posthogAgentsBaseUrl()`
 * with the user's OAuth bearer token attached server-side. The
 * agent's `spec.auth.mode` controls whether the token is actually
 * required upstream (public-mode agents ignore it).
 *
 * Contract (see `services/agent-ingress/src/triggers/chat.ts`):
 *   POST   /agents/<slug>/run     → { ok, session_id, resumed, principal }
 *   POST   /agents/<slug>/send    → { ok }
 *   POST   /agents/<slug>/cancel  → { ok, idempotent?, state? }
 *   GET    /agents/<slug>/listen  → text/event-stream
 *
 * Preview path: when a `preview` option is supplied, the client
 * keeps the same URL prefix but flips the slug to `<slug>-<revHex>`
 * (the ingress's revision-routing form) and attaches the short-lived
 * JWT Django minted via `getPreviewToken(...)`. POST/DELETE carry it
 * as the `x-agent-preview-token` header; `EventSource` for `/listen`
 * carries it as `?preview_token=` in the URL because the API can't
 * set custom headers. Ingress accepts either source. The runner
 * itself doesn't know "live" vs "preview" — same trigger handlers,
 * same path.
 */

const LIVE_PREFIX = '/api/agents/v1/agents'

export interface PreviewOpts {
    /**
     * Slug to use in the ingress URL — the `<application_slug>-<revHex>`
     * shape that ingress's resolver uses to pick a specific non-live
     * revision. Returned by `getPreviewToken` as `ingress_slug`.
     */
    ingressSlug: string
    /** Short-lived HS256 JWT from `getPreviewToken`. */
    token: string
}

/**
 * Build the ingress URL. For live (`preview == null`) it's just the
 * public chat path. For preview it swaps the slug for the rev-hex form
 * and (for the SSE listen case) appends `preview_token=` in the query
 * — EventSource can't set headers, so the URL is the only channel.
 */
function buildUrl(
    slug: string,
    rest: 'run' | 'send' | 'cancel' | 'listen' | 'client_tool_result',
    preview: PreviewOpts | undefined,
    query: string | undefined,
    embedTokenInQuery: boolean
): string {
    const effectiveSlug = preview?.ingressSlug ?? slug
    const tokenQuery = preview && embedTokenInQuery ? `preview_token=${encodeURIComponent(preview.token)}` : undefined
    const combined = [query, tokenQuery].filter(Boolean).join('&')
    const qs = combined ? `?${combined}` : ''
    return `${LIVE_PREFIX}/${encodeURIComponent(effectiveSlug)}/${rest}${qs}`
}

function previewHeaders(preview?: PreviewOpts): Record<string, string> {
    return preview ? { 'x-agent-preview-token': preview.token } : {}
}

/**
 * Shape of the JSON body the Next.js catch-all proxy + ingress
 * trigger handlers + Django all return on errors. Fields are optional
 * because not every layer fills every key — `error` is a stable string
 * code that callers can branch on (e.g. `upstream_unreachable`,
 * `no_chat_trigger`, `preview_token_required`), `detail` is the
 * human-readable explanation.
 */
export interface IngressErrorBody {
    error?: string
    detail?: string
    /** Underlying upstream URL the proxy was trying to reach. */
    upstream?: string
    [k: string]: unknown
}

export class IngressError extends Error {
    readonly status: number
    /** Parsed JSON body when the response was JSON; `null` otherwise. */
    readonly body: IngressErrorBody | null
    constructor(status: number, message: string, body: IngressErrorBody | null = null) {
        super(message)
        this.status = status
        this.body = body
        this.name = 'IngressError'
    }
}

async function postJson<TBody, TResult>(
    url: string,
    body: TBody,
    extraHeaders: Record<string, string> = {}
): Promise<TResult> {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...extraHeaders },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        const text = await res.text().catch(() => '')
        // Try to parse the body as JSON so callers can branch on
        // `body.error`. Many endpoints return plain text or HTML on
        // server errors; preserve the raw text in `message` for those.
        let parsedBody: IngressErrorBody | null = null
        try {
            const maybe = JSON.parse(text)
            if (maybe && typeof maybe === 'object') {
                parsedBody = maybe as IngressErrorBody
            }
        } catch {
            // Not JSON — leave parsedBody null.
        }
        throw new IngressError(res.status, `${res.status} ${res.statusText}: ${text}`, parsedBody)
    }
    return (await res.json()) as TResult
}

export interface RunResponse {
    ok: true
    session_id: string
    resumed: boolean
    principal: unknown
}

export async function startRun(
    slug: string,
    message: string,
    opts: { externalKey?: string; preview?: PreviewOpts } = {}
): Promise<RunResponse> {
    return postJson<{ message: string; external_key?: string }, RunResponse>(
        buildUrl(slug, 'run', opts.preview, undefined, false),
        opts.externalKey ? { message, external_key: opts.externalKey } : { message },
        previewHeaders(opts.preview)
    )
}

export async function sendMessage(
    slug: string,
    sessionId: string,
    message: string,
    opts: { preview?: PreviewOpts } = {}
): Promise<{ ok: true }> {
    return postJson<{ session_id: string; message: string }, { ok: true }>(
        buildUrl(slug, 'send', opts.preview, undefined, false),
        { session_id: sessionId, message },
        previewHeaders(opts.preview)
    )
}

/**
 * Post an interactive client-tool outcome via `/send`. Routes to the
 * pending_inputs marker path; the runner injects a wake message on
 * resume. Sync tools use `postClientToolResult` (bus) instead.
 */
export async function sendClientToolResult(
    slug: string,
    sessionId: string,
    callId: string,
    body: { result: Record<string, unknown> } | { error: string },
    opts: { preview?: PreviewOpts } = {}
): Promise<{ ok: true }> {
    const payload =
        'error' in body
            ? { session_id: sessionId, client_tool_result: { call_id: callId, error: body.error } }
            : { session_id: sessionId, client_tool_result: { call_id: callId, result: body.result } }
    return postJson<typeof payload, { ok: true }>(
        buildUrl(slug, 'send', opts.preview, undefined, false),
        payload,
        previewHeaders(opts.preview)
    )
}

export async function cancelSession(
    slug: string,
    sessionId: string,
    opts: { preview?: PreviewOpts } = {}
): Promise<{ ok: true; idempotent?: boolean; state?: string }> {
    return postJson<{ session_id: string }, { ok: true; idempotent?: boolean; state?: string }>(
        buildUrl(slug, 'cancel', opts.preview, undefined, false),
        { session_id: sessionId },
        previewHeaders(opts.preview)
    )
}

/**
 * Post the result of a client-fulfilled tool call back to ingress. The
 * runner is awaiting a matching `client_tool_result` bus event keyed by
 * `call_id`; this POST publishes it. Exactly one of `result` / `error`
 * must be set.
 */
export async function postClientToolResult(
    slug: string,
    sessionId: string,
    callId: string,
    body: { result: unknown } | { error: string },
    opts: { preview?: PreviewOpts } = {}
): Promise<{ ok: true }> {
    const payload =
        'error' in body
            ? { session_id: sessionId, call_id: callId, error: body.error }
            : { session_id: sessionId, call_id: callId, result: body.result }
    return postJson<typeof payload, { ok: true }>(
        buildUrl(slug, 'client_tool_result', opts.preview, undefined, false),
        payload,
        previewHeaders(opts.preview)
    )
}

/**
 * Subscribe to the SSE stream for one session. Returns a close fn.
 * The listener receives every event the runner publishes for the
 * session — see `SessionEvent` for the kind catalogue.
 */
export interface SessionEvent {
    session_id: string
    kind: string
    data: Record<string, unknown>
    ts: string
}

export interface ListenHandlers {
    onEvent: (event: SessionEvent) => void
    /** Fires only when retries are exhausted or the stream closed terminally. */
    onError?: (err: unknown) => void
    /**
     * Fires when the underlying EventSource is in the middle of a
     * reconnect attempt (after a successful prior open). The UI can
     * render a quiet "Reconnecting…" pill; we don't surface it as a
     * full transport error unless retries also fail.
     */
    onReconnecting?: (attempt: number) => void
}

/**
 * Reconnect strategy: exponential backoff with cap + max attempts.
 * Ingress doesn't currently support `Last-Event-ID` replay (events
 * carry no `id:` field), so on reconnect we just re-open a fresh
 * stream and any events that landed during the gap are missed.
 * Acceptable for chat — the run keeps going server-side; the UI just
 * shows a small tail-gap. A future ingress change can swap this for
 * true resume-from-id by emitting `id:` lines.
 */
const RECONNECT_MAX_ATTEMPTS = 5
const RECONNECT_BASE_DELAY_MS = 750
const RECONNECT_MAX_DELAY_MS = 8_000

export function listen(
    slug: string,
    sessionId: string,
    handlers: ListenHandlers,
    opts: { preview?: PreviewOpts } = {}
): () => void {
    // `true` → embed `preview_token=` in the query string; EventSource
    // can't set the `x-agent-preview-token` header so the URL is the
    // only channel for the JWT. Ingress accepts either source.
    const url = buildUrl(slug, 'listen', opts.preview, `session_id=${encodeURIComponent(sessionId)}`, true)

    let attempt = 0
    let openedAtLeastOnce = false
    let closed = false
    let source: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const cleanup = (): void => {
        if (source) {
            source.close()
            source = null
        }
        if (reconnectTimer !== null) {
            clearTimeout(reconnectTimer)
            reconnectTimer = null
        }
    }

    const open = (): void => {
        source = new EventSource(url)
        source.addEventListener('open', () => {
            openedAtLeastOnce = true
            attempt = 0
        })
        source.addEventListener('message', (e: MessageEvent) => {
            try {
                handlers.onEvent(JSON.parse(e.data) as SessionEvent)
            } catch (err) {
                handlers.onError?.(err)
            }
        })
        source.addEventListener('error', () => {
            if (closed) {
                return
            }
            // EventSource.CLOSED (2) means the browser gave up — usually
            // because the response carried a 4xx that EventSource can't
            // recover from. Surface immediately; no point retrying.
            const terminal = source?.readyState === EventSource.CLOSED
            cleanup()
            // Never-opened → the very first connection failed, surface
            // as a transport error straight away (likely 4xx). Stream
            // dropped after open → reconnect within budget.
            if (terminal || !openedAtLeastOnce || attempt >= RECONNECT_MAX_ATTEMPTS) {
                handlers.onError?.(new Event('error'))
                return
            }
            attempt += 1
            handlers.onReconnecting?.(attempt)
            const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** (attempt - 1), RECONNECT_MAX_DELAY_MS)
            reconnectTimer = setTimeout(() => {
                reconnectTimer = null
                if (!closed) {
                    open()
                }
            }, delay)
        })
    }

    open()

    return () => {
        closed = true
        cleanup()
    }
}

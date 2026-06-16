/**
 * Catch-all API proxy → PostHog Django (+ later agent-ingress).
 *
 * Browser hits same-origin `/api/projects/...` — this handler reads the
 * sealed session cookie, attaches `Authorization: Bearer <access_token>`,
 * and forwards the request to the right upstream. The token never
 * reaches the browser; cookies stay HTTP-only.
 *
 * Routing:
 *   `/api/agents/v1/...` → `posthogAgentsBaseUrl()` (agent-ingress)
 *   `/api/...`           → `posthogBaseUrl()` (PostHog Django)
 *
 * On 401: try to refresh the access_token using the refresh_token,
 * then replay the request once. If refresh also fails we clear the
 * session and surface 401 to the browser (the middleware redirects
 * the next navigation back to /login).
 *
 * Streaming-aware: passes through response bodies as-is so SSE
 * (`text/event-stream`) Just Works without buffering.
 *
 * The `/api/auth/*` routes are NOT handled here — Next.js routes those
 * to their own handlers first because they're more specific paths.
 */

import { NextRequest, NextResponse } from 'next/server'

import { clearSession, getSession, setSession, type SessionPayload } from '@/lib/auth/session'
import { OAuthTokenError, refreshAccessToken } from '@/lib/auth/tokens'
import { getConfig } from '@/lib/config'

export const dynamic = 'force-dynamic'

const HANDLED_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const

/**
 * Agent slug charset — mirrors Django's slug validation plus the optional
 * `-<revision-hex>` suffix the ingress resolver accepts. In domain mode the
 * slug becomes the authority of the upstream URL, so a `#`, `/`, `@`, `?` or
 * `\` in it could redirect the server-side fetch to an unintended host.
 * Reject anything outside this set before composing the URL.
 */
const AGENT_SLUG_RE = /^[a-z0-9][a-z0-9-]{0,61}([a-z0-9]|-[0-9a-f]{8,32})?$/

class InvalidSlugError extends Error {
    constructor(readonly slug: string) {
        super('invalid_slug')
        this.name = 'InvalidSlugError'
    }
}

async function handle(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }): Promise<Response> {
    const { path } = await params
    const segments = path ?? []

    // Defensive: `/api/auth/*` is supposed to be handled by its own
    // routes — but if Next.js's routing ever overlaps, bail loudly
    // rather than proxying upstream and confusing things.
    if (segments[0] === 'auth') {
        return NextResponse.json({ error: 'unhandled_auth_route' }, { status: 404 })
    }

    const session = await getSession()
    if (!session) {
        return NextResponse.json({ error: 'unauthenticated' }, { status: 401 })
    }

    let upstream: UpstreamTarget
    try {
        upstream = buildUpstreamUrl(segments, request.nextUrl.search)
    } catch (err) {
        if (err instanceof InvalidSlugError) {
            return NextResponse.json({ error: 'invalid_slug' }, { status: 400 })
        }
        throw err
    }
    const init = await buildRequestInit(request)

    const first = await proxy(upstream.url, init, session)
    if (first.status !== 401) {
        return first
    }

    // 401 — try one refresh + replay.
    let refreshed: SessionPayload
    try {
        refreshed = await refreshAccessToken(session.refreshToken)
    } catch (err) {
        if (err instanceof OAuthTokenError && (err.status === 400 || err.status === 401)) {
            await clearSession()
        }
        return NextResponse.json({ error: 'unauthenticated' }, { status: 401 })
    }
    // Preserve cookie-side metadata (teamId, sub) that the refresh
    // response doesn't carry — otherwise the next /api/auth/me lands on
    // teamId=null and the UI shows "no current project".
    const merged: SessionPayload = { ...session, ...refreshed }
    await setSession(merged)

    // Body is a stream that may have been consumed; rebuild from the
    // original request (cheap because Next has the body buffered for
    // the route handler).
    const replayInit = await buildRequestInit(request)
    return await proxy(upstream.url, replayInit, merged)
}

interface UpstreamTarget {
    url: string
}

function buildUpstreamUrl(segments: string[], search: string): UpstreamTarget {
    const { posthogAgentsBaseUrl, posthogBaseUrl, agentIngressRoutingMode, agentIngressDomainSuffix } = getConfig()
    if (segments[0] === 'agents' && segments[1] === 'v1') {
        const rest = segments.slice(2)
        // Domain mode: the ingress mounts trigger routes at root and reads the
        // slug from the Host. We can't override `Host` on a fetch (it's a
        // forbidden header — silently dropped), so we dial the agent's public
        // domain directly, making the authority the Host. Rewrite
        // `agents/<slug>/<route>` → `https://<slug><suffix>/<route>`. Fall back
        // to the path form when the shape doesn't match or no suffix is set.
        if (agentIngressRoutingMode === 'domain' && agentIngressDomainSuffix && rest[0] === 'agents' && rest[1]) {
            const slug = rest[1]
            if (!AGENT_SLUG_RE.test(slug)) {
                throw new InvalidSlugError(slug)
            }
            const route = rest.slice(2).join('/')
            return { url: `https://${slug}${agentIngressDomainSuffix}/${route}${search}` }
        }
        return { url: `${posthogAgentsBaseUrl}/${rest.join('/')}${search}` }
    }
    return { url: `${posthogBaseUrl}/api/${segments.join('/')}${search}` }
}

async function buildRequestInit(request: NextRequest): Promise<RequestInit> {
    const headers = new Headers()
    request.headers.forEach((value, key) => {
        const lower = key.toLowerCase()
        // Strip hop-by-hop + cookie headers — the upstream auth is the
        // bearer token, not whatever cookies the browser may also send.
        if (
            lower === 'host' ||
            lower === 'cookie' ||
            lower === 'connection' ||
            lower === 'content-length' ||
            lower === 'authorization'
        ) {
            return
        }
        headers.set(key, value)
    })

    const init: RequestInit = {
        method: request.method,
        headers,
        // @ts-expect-error — `duplex` is required by Node fetch for streamed bodies
        duplex: 'half',
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
        const body = await request.arrayBuffer()
        if (body.byteLength > 0) {
            init.body = body
        }
    }

    return init
}

async function proxy(url: string, init: RequestInit, session: SessionPayload): Promise<Response> {
    const headers = new Headers(init.headers)
    headers.set('Authorization', `Bearer ${session.accessToken}`)
    try {
        const res = await fetch(url, { ...init, headers })
        // undici transparently decompresses the upstream body, but the
        // `content-encoding` / `content-length` headers still describe the
        // *compressed* bytes. Forwarding them makes the browser try to gunzip
        // already-plaintext JSON (ERR_CONTENT_DECODING_FAILED) — which only
        // bites once a response is big enough for Django to gzip it (e.g. the
        // `/query/` rollups). Strip them; keep the body stream so SSE still
        // passes through unbuffered.
        const outHeaders = new Headers(res.headers)
        outHeaders.delete('content-encoding')
        outHeaders.delete('content-length')
        return new Response(res.body, { status: res.status, statusText: res.statusText, headers: outHeaders })
    } catch (err) {
        // Network-layer failure — upstream is down, DNS failed, etc.
        // Surface as a clean 502 with an actionable body so the dock
        // can render "Agent platform unreachable" instead of a generic
        // 500.
        return NextResponse.json(
            {
                error: 'upstream_unreachable',
                upstream: url,
                detail: err instanceof Error ? err.message : String(err),
            },
            { status: 502 }
        )
    }
}

export const GET = handle
export const POST = handle
export const PUT = handle
export const PATCH = handle
export const DELETE = handle

void HANDLED_METHODS

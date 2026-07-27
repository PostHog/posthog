/**
 * Chat trigger: POST /run starts a new session, POST /send appends to an
 * existing one, GET /listen streams events (SSE), POST /cancel cancels, and
 * POST /client_tool_result answers a runner-emitted client tool call. Used by
 * the in-PostHog chat scene and any HTTP client that wants a thread-shaped
 * conversation.
 *
 * Auth: every route is `agent_spec` — the mount guard runs the agent's auth
 * modes before the handler, so each handler receives an authenticated
 * `principal`. The write/stream paths additionally enforce session ownership
 * (ACL) on the principal the guard produced.
 *
 * Edge admission: when the agent declares an `authoritative_provider`, EVERY
 * session-touching route (`/run`, `/send`, `/cancel`, `/listen`,
 * `/client_tool_result`) must additionally resolve a verified canonical
 * identity for the principal before touching the session — unauthenticated
 * callers get `401 { auth_required }` with a link (see `admitChatPrincipal`).
 * Admission also stamps `canonical_agent_user_id` on the principal, which the
 * ACL's canonical match requires, so skipping it on any route would 403 the
 * legitimate owner of an admitted session.
 */

import { z } from 'zod'

import { buildClientToolResultMarker, createLogger, TRIGGER_ROUTES, type SessionPrincipal } from '@posthog/agent-shared'

const log = createLogger('chat-trigger')

import { buildElevationResponse, principalDisplay, recordElevationRequest, requireAclAccess } from '../enqueue/acl'
import { buildAdmission, httpTransportClaim } from '../enqueue/admission-gate'
import { readBearer } from '../enqueue/auth'
import { enqueueOrResume } from '../enqueue/enqueue'
import { activeStreams } from '../metrics'
import {
    ChatCancelBodySchema,
    ChatClientToolResultBodySchema,
    ChatListenQuerySchema,
    ChatRunBodySchema,
    ChatSendBodySchema,
} from './chat.schemas'
import { getOwnedSession } from './session-access'
import { defineRoute, type AuthedRouteCtx, type TriggerModule } from './types'

/**
 * Edge admission for the HTTP/chat transport (mirrors the Slack trigger): if
 * the agent declares an authoritative provider, the claim must resolve a
 * verified identity BEFORE any session work. Unauthenticated → respond
 * `401 { auth_required, provider, authorize_url }`; a principal that cannot
 * carry a per-user claim (anonymous/machine) → 403; provider/config error →
 * fail closed with a 500. Returns the principal to use downstream — stamped
 * with `canonical_agent_user_id` when admitted — or null when the response
 * has already been written.
 */
async function admitChatPrincipal(ctx: AuthedRouteCtx<unknown>): Promise<SessionPrincipal | null> {
    const { req, res, deps, resolved } = ctx
    const admission = buildAdmission(deps, resolved.revision, resolved.application.slug)
    if (!admission) {
        return ctx.principal
    }
    const claim = httpTransportClaim(ctx.principal, readBearer(req), resolved.revision)
    if (!claim) {
        // Machine principals and the public opt-in anonymous principal carry no
        // per-sender human identity to verify (see `httpTransportClaim`), and
        // the authoritative gate is absolute: fail closed rather than let a
        // coexisting public/shared-secret/internal auth mode silently void it.
        // An agent that wants machine or anonymous callers must not declare an
        // authoritative_provider.
        res.status(403).json({ error: 'admission_unsupported_principal', principal_kind: ctx.principal.kind })
        return null
    }
    const result = await admission.resolve(claim, {
        application: resolved.application,
        revision: resolved.revision,
    })
    if (result.kind === 'auth_required') {
        // Unlike Slack (which must 200 to stop retries and delivers the link
        // out-of-band), HTTP callers get the auth block in the response itself.
        res.status(401).json({
            error: 'auth_required',
            auth_required: true,
            provider: result.provider,
            authorize_url: result.authorizeUrl,
        })
        return null
    }
    if (result.kind === 'error') {
        log.warn({ slug: resolved.application.slug, reason: result.reason }, 'chat_admission_error')
        // Provider unavailability (userinfo down/timeout) is retryable — the
        // caller's token may be perfectly valid — so answer 503, not 500.
        const status = result.reason === 'authoritative_provider_unavailable' ? 503 : 500
        res.status(status).json({ error: 'admission_failed', reason: result.reason })
        return null
    }
    if (result.kind === 'admitted' && (ctx.principal.kind === 'posthog' || ctx.principal.kind === 'jwt')) {
        return { ...ctx.principal, canonical_agent_user_id: result.identity.canonicalId }
    }
    return ctx.principal
}

async function runHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatRunBodySchema>>): Promise<void> {
    const { res, deps, resolved } = ctx
    const { message, external_key: externalKey = null, supported_client_tools: supportedClientTools } = ctx.parsed
    const sessionPrincipal = await admitChatPrincipal(ctx)
    if (!sessionPrincipal) {
        return
    }
    const outcome = await enqueueOrResume(
        { queue: deps.queue },
        {
            application: resolved.application,
            revision: resolved.revision,
            externalKey,
            seed: { role: 'user', content: message, timestamp: Date.now(), sender: sessionPrincipal },
            principal: sessionPrincipal,
            trigger: 'chat',
            requesterDisplay: principalDisplay(sessionPrincipal),
            triggerMetadata: {
                kind: 'chat',
                ...(supportedClientTools?.length ? { supported_client_tools: supportedClientTools } : {}),
            },
            prepareSession: (sessionId) => deps.broker.writeWithRollback(sessionId, ctx.credentials),
        }
    )
    if (outcome.kind === 'elevation_required') {
        res.status(403).json({
            error: 'elevation_required',
            elevation_request_id: outcome.elevationRequestId,
            session_id: outcome.sessionId,
            owner_display: outcome.existingPrincipalDisplay,
        })
        return
    }
    res.json({
        ok: true,
        session_id: outcome.sessionId,
        resumed: outcome.isResume,
        principal: sessionPrincipal,
    })
}

async function sendHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatSendBodySchema>>): Promise<void> {
    const { res, deps, resolved } = ctx
    const { session_id: sessionId, message, client_tool_result } = ctx.parsed
    // Admission runs per message (like the Slack path) and before the session
    // lookup, so a revoked binding stops advancing a session — and an
    // unadmitted caller can't probe session ids through the 404.
    const incomingPrincipal = await admitChatPrincipal(ctx)
    if (!incomingPrincipal) {
        return
    }
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    // Strict principal match: the guard authenticated the caller; compare to
    // the principal stored at /run time.
    const aclCheck = requireAclAccess(existing, incomingPrincipal)
    if (aclCheck.kind === 'denied') {
        const proposed: string =
            message ??
            (client_tool_result ? `[client_tool_result for ${client_tool_result.call_id}]` : '[unknown payload]')
        const elevation = await recordElevationRequest(deps.queue, existing, {
            requester: incomingPrincipal,
            requesterDisplay: principalDisplay(incomingPrincipal),
            trigger: 'chat',
            proposedMessage: {
                role: 'user',
                content: proposed,
                timestamp: Date.now(),
                sender: incomingPrincipal,
            },
        })
        res.status(403).json(buildElevationResponse(existing, elevation))
        return
    }
    // Terminal-state policy (see session-restart redesign):
    //   - `failed` / `cancelled`: always 410. Restarting either would likely
    //     just re-fail or re-cancel.
    //   - `closed`: 410 unless the chat trigger spec opts into `allow_restart`.
    //   - `completed` / `queued` / `running`: append the message, re-queue.
    //     `completed` is open by design.
    if (existing.state === 'failed' || existing.state === 'cancelled') {
        res.status(410).json({ error: 'session_terminal', state: existing.state })
        return
    }
    if (existing.state === 'closed') {
        const chatTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'chat')
        const allowRestart = chatTrigger?.type === 'chat' ? (chatTrigger.config.allow_restart ?? false) : false
        if (!allowRestart) {
            res.status(410).json({ error: 'session_terminal', state: 'closed' })
            return
        }
    }
    // Refresh credentials before re-queueing so a worker can never claim this
    // turn in the gap between the state transition and the broker write. If a
    // queue mutation fails, restore the previous map only while this write is
    // still current, so a concurrent successful refresh is never overwritten.
    const credentialWrite = await deps.broker.writeWithRollback(sessionId, ctx.credentials)
    try {
        if (client_tool_result) {
            const payload = client_tool_result.error
                ? { call_id: client_tool_result.call_id, error: client_tool_result.error }
                : {
                      call_id: client_tool_result.call_id,
                      result: (client_tool_result.result ?? {}) as Record<string, unknown>,
                  }
            await deps.queue.appendPendingInput(sessionId, {
                role: 'user',
                content: buildClientToolResultMarker(payload),
                timestamp: Date.now(),
                sender: incomingPrincipal,
            })
        } else {
            await deps.queue.appendPendingInput(sessionId, {
                role: 'user',
                content: message!,
                timestamp: Date.now(),
                sender: incomingPrincipal,
            })
        }
        await deps.queue.update(sessionId, { state: 'queued' })
    } catch (err) {
        try {
            await credentialWrite.rollback()
        } catch (rollbackError) {
            throw new AggregateError([err, rollbackError], 'credential rollback failed')
        }
        throw err
    }
    res.json({ ok: true })
}

async function cancelHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatCancelBodySchema>>): Promise<void> {
    const { res, deps } = ctx
    const { session_id: sessionId } = ctx.parsed
    // Admission first (mirrors /send): an admitted session's stored principal
    // carries canonical_agent_user_id, so ACL only recognises the owner once
    // the incoming principal is stamped too — and a revoked binding loses
    // control of the session, not just the ability to advance it.
    const incomingPrincipal = await admitChatPrincipal(ctx)
    if (!incomingPrincipal) {
        return
    }
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    if (requireAclAccess(existing, incomingPrincipal).kind === 'denied') {
        res.status(403).json({ error: 'forbidden' })
        return
    }
    // Cancel is idempotent: terminal sessions return ok without changing state.
    if (existing.state === 'closed' || existing.state === 'failed' || existing.state === 'cancelled') {
        res.json({ ok: true, idempotent: true, state: existing.state })
        return
    }
    // Two signals, deliberately both:
    //   - The bus event interrupts a session a worker is *actively
    //     running* — it's subscribed to this channel (same path it
    //     reads `client_tool_result` on) and aborts the in-flight
    //     provider call, then reopens as `completed`.
    //   - The `cancelled` state write is the durable backstop. A
    //     queued session never claimed stays `cancelled` (terminal);
    //     a running session the runner reopens overwrites it with
    //     `completed`. It also closes the publish/subscribe race — a
    //     cancel that lands in the gap between claim and subscribe is
    //     caught by the runner's start-of-run state recheck.
    // Best-effort: the publish only matters for an actively-running worker, so
    // a Redis hiccup must not skip the durable `cancelled` write below.
    try {
        await deps.bus.publish({
            session_id: sessionId,
            kind: 'cancel',
            data: {},
            ts: new Date().toISOString(),
        })
    } catch {
        // Swallow — the state write is the durable cancel signal.
    }
    await deps.queue.update(sessionId, { state: 'cancelled' })
    res.json({ ok: true, state: 'cancelled' })
}

async function listenHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatListenQuerySchema>>): Promise<void> {
    const { req, res, deps, resolved } = ctx
    const { session_id: sessionId } = ctx.parsed
    // Admission first (mirrors /send): stamps canonical_agent_user_id so ACL
    // recognises the admitted owner, and a revoked binding can no longer
    // replay the conversation.
    const incomingPrincipal = await admitChatPrincipal(ctx)
    if (!incomingPrincipal) {
        return
    }
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    // The stream replays the whole conversation, so gate it the same as the
    // write paths. EventSource can't set headers, so the bearer rides in
    // `?token=` (handled in readBearer, which the guard already consumed).
    if (requireAclAccess(existing, incomingPrincipal).kind === 'denied') {
        res.status(403).json({ error: 'forbidden' })
        return
    }
    res.setHeader('Content-Type', 'text/event-stream')
    res.setHeader('Cache-Control', 'no-cache')
    res.setHeader('Connection', 'keep-alive')
    res.flushHeaders()
    activeStreams.labels({ transport: 'chat' }).inc()
    // `closed` is the single flag that gates both the bus callback and the
    // expiry timer. The bus delivers events synchronously into the subscribe
    // callback, but a publish that's already in flight when we unsubscribe
    // can still land here — guarding `res.write` on `closed` is what makes
    // it safe to end the response from the expiry path.
    let closed = false
    let expiryTimer: NodeJS.Timeout | undefined
    const unsubscribe = deps.bus.subscribe(sessionId, (event) => {
        if (closed) {
            return
        }
        res.write(`data: ${JSON.stringify(event)}\n\n`)
    })
    // Keepalive: a comment frame every 20s keeps bytes flowing while the agent
    // is mid-turn and emitting no events, so a proxy idle/response timeout
    // (Envoy stream-idle, ALB) can't reset the stream and surface as a "network
    // error" in the client. The client's SSE parser keeps only `data:` lines,
    // so comment frames are discarded. unref() so it never blocks shutdown.
    const heartbeat = setInterval(() => {
        if (closed) {
            return
        }
        res.write(': keepalive\n\n')
    }, 20_000)
    heartbeat.unref()
    const cleanup = (): void => {
        if (closed) {
            return
        }
        closed = true
        unsubscribe()
        activeStreams.labels({ transport: 'chat' }).dec()
        clearInterval(heartbeat)
        if (expiryTimer) {
            clearTimeout(expiryTimer)
        }
    }
    // Preview-mode streams: pre-emit `preview_token_required` at the JWT's
    // expiry instead of letting the connection drop silently. The client
    // (posthog/code agent-builder) handles the event by re-minting via
    // `POST .../preview-token/` and re-attaching `/listen` transparently —
    // the agent builder UI never shows a generic disconnect during a long
    // author session.
    //
    // Skew margin (5s): fire just before the upstream `exp` so the client
    // has a window to re-mint while its existing JWT is still valid for the
    // POST. Caps the scheduled delay at the v8 setTimeout 32-bit ceiling
    // (~24.8 days) — the 15-min TTL never approaches it, but a future
    // longer-lived token wouldn't silently overflow into "fire immediately."
    if (resolved.previewJwtExp !== null) {
        const skewMs = 5_000
        const delayMs = Math.min(Math.max(0, resolved.previewJwtExp * 1000 - Date.now() - skewMs), 2_147_483_647)
        expiryTimer = setTimeout(() => {
            if (closed) {
                return
            }
            res.write(
                `data: ${JSON.stringify({
                    session_id: sessionId,
                    kind: 'preview_token_required',
                    data: { reason: 'expired' },
                    ts: new Date().toISOString(),
                })}\n\n`
            )
            // Unsubscribe before `res.end()` so a bus event arriving in the
            // window between end-of-response and the `close` event firing
            // can't reach `res.write` on the ended stream.
            cleanup()
            res.end()
        }, delayMs)
    }
    req.on('close', cleanup)
}

async function clientToolResultHandler(
    ctx: AuthedRouteCtx<z.infer<typeof ChatClientToolResultBodySchema>>
): Promise<void> {
    const { res, deps } = ctx
    const { session_id: sessionId, call_id, result, error } = ctx.parsed
    // Admission first (mirrors /send): stamps canonical_agent_user_id so ACL
    // recognises the admitted owner of the running turn.
    const incomingPrincipal = await admitChatPrincipal(ctx)
    if (!incomingPrincipal) {
        return
    }
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'no_session' })
        return
    }
    // A tool result feeds straight into the running turn — confirm session
    // ownership before publishing it.
    if (requireAclAccess(existing, incomingPrincipal).kind === 'denied') {
        res.status(403).json({ error: 'forbidden' })
        return
    }
    await deps.bus.publish({
        session_id: sessionId,
        kind: 'client_tool_result',
        data: error ? { call_id, error } : { call_id, result },
        ts: new Date().toISOString(),
    })
    res.json({ ok: true })
}

/**
 * Chat trigger module. The `auth` on each route is enforced by the mount guard
 * (see `mount.ts`) and published verbatim by `GET /agents/<slug>/schemas`.
 */
export const chatTrigger: TriggerModule = {
    type: 'chat',
    routes: [
        defineRoute({
            method: 'POST',
            path: TRIGGER_ROUTES.chat.run,
            auth: 'agent_spec',
            schema: ChatRunBodySchema,
            handler: runHandler,
        }),
        defineRoute({
            method: 'POST',
            path: TRIGGER_ROUTES.chat.send,
            auth: 'agent_spec',
            schema: ChatSendBodySchema,
            handler: sendHandler,
        }),
        defineRoute({
            method: 'POST',
            path: TRIGGER_ROUTES.chat.cancel,
            auth: 'agent_spec',
            schema: ChatCancelBodySchema,
            handler: cancelHandler,
        }),
        defineRoute({
            method: 'GET',
            path: TRIGGER_ROUTES.chat.listen,
            auth: 'agent_spec',
            schema: ChatListenQuerySchema,
            handler: listenHandler,
        }),
        defineRoute({
            method: 'POST',
            path: TRIGGER_ROUTES.chat.client_tool_result,
            auth: 'agent_spec',
            schema: ChatClientToolResultBodySchema,
            handler: clientToolResultHandler,
        }),
    ],
}

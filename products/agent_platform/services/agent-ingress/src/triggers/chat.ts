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
 */

import { z } from 'zod'

import { buildClientToolResultMarker, TRIGGER_ROUTES } from '@posthog/agent-shared'

import { buildElevationResponse, principalDisplay, recordElevationRequest, requireAclAccess } from '../enqueue/acl'
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

async function runHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatRunBodySchema>>): Promise<void> {
    const { res, deps, resolved } = ctx
    const { message, external_key: externalKey = null, supported_client_tools: supportedClientTools } = ctx.parsed
    const sessionPrincipal = ctx.principal
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
    // Write per-session auth materials into the broker keyed by the freshly
    // minted session id. Tools resolve through this at call time; nothing
    // token-bearing lands on the session row.
    await deps.broker.write(outcome.sessionId, ctx.credentials)
    res.json({
        ok: true,
        session_id: outcome.sessionId,
        resumed: outcome.isResume,
        principal: ctx.principal,
    })
}

async function sendHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatSendBodySchema>>): Promise<void> {
    const { res, deps, resolved } = ctx
    const { session_id: sessionId, message, client_tool_result } = ctx.parsed
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    // Strict principal match: the guard authenticated the caller; compare to
    // the principal stored at /run time.
    const incomingPrincipal = ctx.principal
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
    // Refresh broker creds with whatever the client just supplied — OAuth
    // tokens may have rotated since /run, and the worker may have evicted the
    // prior entry.
    await deps.broker.write(sessionId, ctx.credentials)
    res.json({ ok: true })
}

async function cancelHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatCancelBodySchema>>): Promise<void> {
    const { res, deps } = ctx
    const { session_id: sessionId } = ctx.parsed
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    if (requireAclAccess(existing, ctx.principal).kind === 'denied') {
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
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    // The stream replays the whole conversation, so gate it the same as the
    // write paths. EventSource can't set headers, so the bearer rides in
    // `?token=` (handled in readBearer, which the guard already consumed).
    if (requireAclAccess(existing, ctx.principal).kind === 'denied') {
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
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'no_session' })
        return
    }
    // A tool result feeds straight into the running turn — confirm session
    // ownership before publishing it.
    if (requireAclAccess(existing, ctx.principal).kind === 'denied') {
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

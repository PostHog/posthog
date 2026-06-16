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

import { buildClientToolResultMarker } from '@posthog/agent-shared'

import { buildElevationResponse, principalDisplay, recordElevationRequest, requireAclAccess } from '../enqueue/acl'
import { enqueueOrResume } from '../enqueue/enqueue'
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
    const { message, external_key: externalKey = null } = ctx.parsed
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
    await deps.queue.update(sessionId, { state: 'cancelled' })
    res.json({ ok: true, state: 'cancelled' })
}

async function listenHandler(ctx: AuthedRouteCtx<z.infer<typeof ChatListenQuerySchema>>): Promise<void> {
    const { req, res, deps } = ctx
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
    const unsubscribe = deps.bus.subscribe(sessionId, (event) => {
        res.write(`data: ${JSON.stringify(event)}\n\n`)
    })
    req.on('close', () => unsubscribe())
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
            path: '/run',
            auth: 'agent_spec',
            schema: ChatRunBodySchema,
            handler: runHandler,
        }),
        defineRoute({
            method: 'POST',
            path: '/send',
            auth: 'agent_spec',
            schema: ChatSendBodySchema,
            handler: sendHandler,
        }),
        defineRoute({
            method: 'POST',
            path: '/cancel',
            auth: 'agent_spec',
            schema: ChatCancelBodySchema,
            handler: cancelHandler,
        }),
        defineRoute({
            method: 'GET',
            path: '/listen',
            auth: 'agent_spec',
            schema: ChatListenQuerySchema,
            handler: listenHandler,
        }),
        defineRoute({
            method: 'POST',
            path: '/client_tool_result',
            auth: 'agent_spec',
            schema: ChatClientToolResultBodySchema,
            handler: clientToolResultHandler,
        }),
    ],
}

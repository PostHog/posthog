/**
 * Generic webhook trigger. Body is delivered verbatim as the agent's first
 * user message (JSON-stringified). Used for arbitrary integrations.
 *
 * Auth is `agent_spec`: the mount guard runs the agent's `spec.auth` before
 * the handler, which receives the authenticated principal and captures it on
 * the session for later strict-match enforcement.
 */

import { Request } from 'express'
import { createHash } from 'node:crypto'
import type { z } from 'zod'

import { principalDisplay } from '../enqueue/acl'
import { enqueueOrResume } from '../enqueue/enqueue'
import { defineRoute, type AuthedRouteCtx, type TriggerModule } from './types'
import { WebhookBodySchema } from './webhook.schemas'

async function webhookHandler(ctx: AuthedRouteCtx<z.infer<typeof WebhookBodySchema>>): Promise<void> {
    const { req, res, deps, resolved } = ctx
    const body = ctx.parsed
    const externalKeyHeader = req.headers['x-external-key']
    const externalKey = typeof externalKeyHeader === 'string' ? externalKeyHeader : null
    const idempotencyKey = extractProviderIdempotencyKey(req, body)
    const sessionPrincipal = ctx.principal
    const outcome = await enqueueOrResume(
        { queue: deps.queue },
        {
            application: resolved.application,
            revision: resolved.revision,
            externalKey,
            idempotencyKey,
            seed: {
                role: 'user',
                content: JSON.stringify(body),
                timestamp: Date.now(),
                sender: sessionPrincipal,
            },
            principal: sessionPrincipal,
            trigger: 'webhook',
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
    res.json({ ok: true, session_id: outcome.sessionId, resumed: outcome.isResume })
}

/**
 * Provider-supplied idempotency keys, in precedence order. First non-empty
 * header wins; absent on all → undefined → no dedupe.
 *
 *   - `Idempotency-Key` is the generic / Stripe-shaped convention. Authors
 *     of custom integrations should use this.
 *   - `X-Idempotency-Key` is the same primitive under the historical
 *     `X-` prefix; common in older integrations.
 *   - `X-GitHub-Delivery` is GitHub's per-event UUID, stable across
 *     redeliveries. (Stripe also has its own `idempotency_key` body field;
 *     payload-shape extraction is out of scope here — that's the agent's
 *     job once it sees the seed, not the platform's.)
 *
 * The returned key is `webhook:<value>:<sha256(payload)>`. The `webhook:`
 * prefix namespaces it away from cron firings. The payload digest defeats
 * a spoof where an attacker with reachability to a public webhook posts
 * first with a guessed header value (e.g. a Stripe event id leaked via
 * a log) so a later legitimate provider delivery dedupes to the attacker's
 * session and drops the real payload — a different body produces a
 * different digest, so legitimate retries (same header + same body) still
 * collapse correctly while spoofs do not. This is defence-in-depth, not a
 * substitute for provider signature verification, which the configured
 * auth provider should still enforce upstream.
 */
function extractProviderIdempotencyKey(req: Request, parsedBody: unknown): string | undefined {
    const candidates = ['idempotency-key', 'x-idempotency-key', 'x-github-delivery']
    for (const name of candidates) {
        const v = req.headers[name]
        const value = typeof v === 'string' ? v : Array.isArray(v) ? v[0] : undefined
        if (value && value.length > 0) {
            const digest = createHash('sha256').update(JSON.stringify(parsedBody)).digest('hex')
            return `webhook:${value}:${digest}`
        }
    }
    return undefined
}

/** The published `bodySchema` is intentionally loose — webhook accepts any
 *  JSON object, and the agent's `agent.md` defines what the *content* of that
 *  object should look like. We do reject null / non-object bodies at the edge
 *  so the seed message isn't `"null"`. */
export const webhookTrigger: TriggerModule = {
    type: 'webhook',
    routes: [
        defineRoute({
            method: 'POST',
            path: '/webhook',
            auth: 'agent_spec',
            schema: WebhookBodySchema,
            handler: webhookHandler,
        }),
    ],
}

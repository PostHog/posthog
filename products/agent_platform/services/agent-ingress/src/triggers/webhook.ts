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

import { createLogger, type Trigger, TRIGGER_ROUTES } from '@posthog/agent-shared'

import { principalDisplay } from '../enqueue/acl'
import { enqueueOrResume } from '../enqueue/enqueue'
import { defineRoute, type AuthedRouteCtx, type TriggerModule } from './types'
import { payloadMatchesFilters } from './webhook-filters'
import { WebhookBodySchema } from './webhook.schemas'

const log = createLogger('webhook-trigger')

async function webhookHandler(ctx: AuthedRouteCtx<z.infer<typeof WebhookBodySchema>>): Promise<void> {
    const { req, res, deps, resolved } = ctx
    // A mislabeled urlencoded Content-Type still passes `WebhookBodySchema` (Express parses the raw JSON into a garbage form object), which would silently become the seed message. Reject explicitly.
    if (req.is('application/json') === false) {
        res.status(400).json({ error: 'invalid_content_type', expected: 'application/json' })
        return
    }
    const body = ctx.parsed
    // Deterministic payload gate, AFTER auth (the mount guard already
    // verified the caller): a non-matching delivery is ACKed 2xx with no
    // session, so chatty providers stay healthy without spending a model
    // session per irrelevant event.
    const trigger = resolved.revision.spec.triggers.find((t) => t.type === 'webhook')
    const filters = trigger?.type === 'webhook' ? trigger.config.filters : undefined
    if (!payloadMatchesFilters(body, filters)) {
        // Log it: a filter whose path never matches (e.g. one that points
        // through an array) silently drops every delivery, and the provider
        // only sees a healthy 200 — this line is the one place that shows why.
        log.info({ slug: resolved.application.slug }, 'webhook_delivery_filtered')
        res.json({ ok: true, filtered: true })
        return
    }
    const externalKeyHeader = req.headers['x-external-key']
    const externalKey = typeof externalKeyHeader === 'string' ? externalKeyHeader : null
    const trigger = resolved.revision.spec.triggers.find((t) => t.type === 'webhook')
    const idempotencyKey = extractIdempotencyKey(req, body, trigger)
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

/**
 * Prefer the verified HMAC signature as the dedup key when the trigger uses an
 * `hmac_sha256` auth mode. The signature is an unforgeable function of the body
 * (the mount guard already verified it before this handler ran), so a replay
 * that resends the same signed body under a fresh `X-GitHub-Delivery` — which
 * is NOT part of the signed content — still collapses to one session, closing
 * the signature-covers-body-only replay window. Falls back to the
 * provider-header key for unsigned deliveries (Stripe id, GitHub delivery, …),
 * whose header+body-digest form defends the separate pre-emption spoof.
 */
function extractIdempotencyKey(req: Request, parsedBody: unknown, trigger: Trigger | undefined): string | undefined {
    if (trigger?.type === 'webhook') {
        for (const mode of trigger.auth.modes) {
            if (mode.type === 'shared_secret' && mode.scheme === 'hmac_sha256') {
                const v = req.headers[mode.header.toLowerCase()]
                const sig = typeof v === 'string' ? v : Array.isArray(v) ? v[0] : undefined
                if (sig && sig.length > 0) {
                    return `webhook:sig:${sig}`
                }
            }
        }
    }
    return extractProviderIdempotencyKey(req, parsedBody)
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
            path: TRIGGER_ROUTES.webhook.post,
            auth: 'agent_spec',
            schema: WebhookBodySchema,
            handler: webhookHandler,
        }),
    ],
}

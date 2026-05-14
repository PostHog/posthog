import { createHmac, timingSafeEqual } from 'node:crypto'

import { ResolvedRevision } from '@posthog/agent-core'
import { Request } from 'ultimate-express'

/**
 * Per-app auth derived from the resolved revision. v1 supports three modes:
 *
 * - `public`            — no auth.
 * - `shared_secret`     — `Authorization: Bearer <token>` checked against `revision.auth.token`.
 * - `webhook_signature` — HMAC-SHA256 over the raw body using `revision.auth.secret`.
 *
 * Webhook signature checks use raw-body access; the server stores the raw buffer on
 * `req.rawBody` via a json verifier in `server.ts`.
 */
export type AuthOutcome = { ok: true } | { ok: false; status: number; message: string }

export interface AuthRequest extends Request {
    rawBody?: Buffer
}

export function authorize(req: AuthRequest, revision: ResolvedRevision): AuthOutcome {
    const auth = revision.auth
    switch (auth.mode) {
        case 'public':
            return { ok: true }
        case 'shared_secret':
            return authorizeSharedSecret(req, auth.token)
        case 'webhook_signature':
            return authorizeWebhookSignature(req, auth.provider, auth.secret)
    }
}

function authorizeSharedSecret(req: AuthRequest, token: string): AuthOutcome {
    const header = req.header('authorization') ?? ''
    const match = header.match(/^Bearer\s+(.+)$/i)
    if (!match) {
        return { ok: false, status: 401, message: 'missing bearer token' }
    }
    if (!constantTimeEqual(match[1], token)) {
        return { ok: false, status: 401, message: 'invalid bearer token' }
    }
    return { ok: true }
}

function authorizeWebhookSignature(req: AuthRequest, provider: string, secret: string): AuthOutcome {
    if (!req.rawBody) {
        return { ok: false, status: 400, message: 'raw body not captured; webhook signature cannot be checked' }
    }
    // v1: provider-agnostic HMAC-SHA256 over the raw body, hex digest, supplied via x-signature.
    // Real provider-specific schemes (Stripe, Slack, GitHub) will land alongside the trigger work.
    const header = req.header('x-signature') ?? ''
    const expected = createHmac('sha256', secret).update(req.rawBody).digest('hex')
    if (!constantTimeEqual(header, expected)) {
        return { ok: false, status: 401, message: `invalid ${provider} webhook signature` }
    }
    return { ok: true }
}

function constantTimeEqual(a: string, b: string): boolean {
    const ab = Buffer.from(a, 'utf8')
    const bb = Buffer.from(b, 'utf8')
    if (ab.length !== bb.length) {
        return false
    }
    return timingSafeEqual(ab, bb)
}

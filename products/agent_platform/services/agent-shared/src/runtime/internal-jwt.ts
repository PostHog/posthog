/**
 * Audience-bound HS256 JWTs for trusted-service ↔ trusted-service calls
 * inside the agent platform. One HMAC key (env: AGENT_INTERNAL_SIGNING_KEY,
 * read by Django + every node service) signs every internal-RPC token;
 * the `aud` claim scopes a token to one receiving service so a token
 * minted for the janitor can't be replayed against the ingress (or vice
 * versa).
 *
 * Audiences today:
 *   - INGRESS_PREVIEW — Django → ingress, draft-revision preview invokes
 *   - JANITOR_RPC     — Django → janitor, bundle CRUD + authoring API
 *
 * Production minting happens on the Django side (posthog/jwt.py:
 * `encode_agent_internal_jwt`). This module is the verify side for the
 * node services, plus a `mintInternalJwt` helper for tests / dev harness
 * / future runner→janitor calls.
 */

import { jwtVerify, SignJWT } from 'jose'
import { randomUUID } from 'node:crypto'

export const INTERNAL_JWT_AUDIENCE = {
    INGRESS_PREVIEW: 'agent-ingress.preview',
    JANITOR_RPC: 'agent-janitor.rpc',
} as const

export type InternalJwtAudience = (typeof INTERNAL_JWT_AUDIENCE)[keyof typeof INTERNAL_JWT_AUDIENCE]

export interface VerifiedInternalJwt {
    sub?: string
    exp?: number
    /** Unique token id — basis for replay detection. Present on tokens minted
     *  after the jti rollout; absent on older tokens (replay check is skipped). */
    jti?: string
    [claim: string]: unknown
}

/**
 * Replay guard for internal JWTs. `aud` + a 60s `exp` already bound the blast
 * radius; this is defence-in-depth so a captured token can't be replayed even
 * within that window. `checkAndRecord` returns true when the jti was already
 * seen (a replay), else records it until it expires.
 */
export interface JtiReplayCache {
    checkAndRecord(jti: string, expEpochSec: number): boolean | Promise<boolean>
}

/**
 * In-memory `JtiReplayCache` — a per-process Map pruned lazily by expiry. Good
 * enough for defence-in-depth at the short (60s) TTL; it does NOT span hosts,
 * so a token replayed to a *different* pod within its TTL isn't caught. A
 * shared (Redis) store would close that, but isn't wired here (the janitor has
 * no Redis) — accepted given the short window.
 */
export class InMemoryJtiReplayCache implements JtiReplayCache {
    private readonly seen = new Map<string, number>()

    checkAndRecord(jti: string, expEpochSec: number): boolean {
        const now = Math.floor(Date.now() / 1000)
        // Opportunistically prune expired entries so the map can't grow without bound.
        for (const [id, exp] of this.seen) {
            if (exp <= now) {
                this.seen.delete(id)
            }
        }
        if (this.seen.has(jti)) {
            return true
        }
        // Keep until the token would have expired anyway (min 1s).
        this.seen.set(jti, Math.max(expEpochSec, now + 1))
        return false
    }
}

export class InternalJwtVerifyError extends Error {
    constructor(readonly reason: string) {
        super(`internal JWT verify failed: ${reason}`)
        this.name = 'InternalJwtVerifyError'
    }
}

export async function verifyInternalJwt(opts: {
    token: string
    audience: InternalJwtAudience
    signingKey: string
    /** When supplied, reject a token whose `jti` was already seen (replay). */
    replayCache?: JtiReplayCache
}): Promise<VerifiedInternalJwt> {
    const keyBytes = new TextEncoder().encode(opts.signingKey)
    let payload: VerifiedInternalJwt
    try {
        const verified = await jwtVerify(opts.token, keyBytes, {
            audience: opts.audience,
            algorithms: ['HS256'],
        })
        payload = verified.payload as VerifiedInternalJwt
    } catch (e) {
        throw new InternalJwtVerifyError((e as Error).message)
    }
    if (opts.replayCache && typeof payload.jti === 'string') {
        // Skip silently when jti is absent (pre-rollout tokens) so deploys
        // stay compatible; aud + exp still gate those.
        const replayed = await opts.replayCache.checkAndRecord(payload.jti, payload.exp ?? 0)
        if (replayed) {
            throw new InternalJwtVerifyError('replayed token (jti already seen)')
        }
    }
    return payload
}

export async function mintInternalJwt(opts: {
    audience: InternalJwtAudience
    signingKey: string
    /** Extra claims placed alongside `aud` + `exp`. */
    claims?: Record<string, unknown>
    /** Token TTL. Default 60s — short by design; mint per call. */
    ttlSec?: number
}): Promise<string> {
    const keyBytes = new TextEncoder().encode(opts.signingKey)
    const ttlSec = opts.ttlSec ?? 60
    return new SignJWT({ ...opts.claims })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(opts.audience)
        .setJti(randomUUID())
        .setExpirationTime(`${ttlSec}s`)
        .sign(keyBytes)
}

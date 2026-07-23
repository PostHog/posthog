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
 *   - INGRESS_RPC     — Django → ingress, internal read RPCs (session digest)
 *   - JANITOR_RPC     — Django → janitor, bundle CRUD + authoring API
 *
 * Production minting happens on the Django side (posthog/jwt.py:
 * `encode_agent_internal_jwt`). This module is the verify side for the
 * node services, plus a `mintInternalJwt` helper for tests / dev harness
 * / future runner→janitor calls.
 */

import { jwtVerify, SignJWT } from 'jose'

export const INTERNAL_JWT_AUDIENCE = {
    INGRESS_PREVIEW: 'agent-ingress.preview',
    INGRESS_RPC: 'agent-ingress.rpc',
    JANITOR_RPC: 'agent-janitor.rpc',
} as const

export type InternalJwtAudience = (typeof INTERNAL_JWT_AUDIENCE)[keyof typeof INTERNAL_JWT_AUDIENCE]

export interface VerifiedInternalJwt {
    sub?: string
    exp?: number
    [claim: string]: unknown
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
}): Promise<VerifiedInternalJwt> {
    const keyBytes = new TextEncoder().encode(opts.signingKey)
    try {
        const { payload } = await jwtVerify(opts.token, keyBytes, {
            audience: opts.audience,
            algorithms: ['HS256'],
        })
        return payload as VerifiedInternalJwt
    } catch (e) {
        throw new InternalJwtVerifyError((e as Error).message)
    }
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
        .setExpirationTime(`${ttlSec}s`)
        .sign(keyBytes)
}

import jwt from 'jsonwebtoken'

import { JWT, PosthogJwtAudience, makeOptionalJwt } from './jwt-utils'

// Mirrors DEFAULT_SERVICE_TOKEN_TTL in posthog/scoped_service_jwt.py.
const DEFAULT_TTL_SECONDS = 5 * 60

// jsonwebtoken tolerates this much clock skew between minter and verifier.
const CLOCK_TOLERANCE_SECONDS = 30

/**
 * One service-to-service auth relationship, Node side. The Python counterpart is
 * ScopedServiceJwtPurpose in posthog/scoped_service_jwt.py; the audience string and claim
 * names must match it exactly, since tokens minted here are verified there (and vice versa).
 *
 * Construct once per purpose from config, then check `enabled` before minting: an empty key
 * string means the purpose's secret is not provisioned in this environment, and callers are
 * expected to fall back to their legacy auth path rather than fail.
 */
export class ScopedServiceJwt {
    private jwt: JWT | null
    private audience: PosthogJwtAudience
    private defaultTtlSeconds: number

    constructor(audience: PosthogJwtAudience, commaSeparatedKeys: string, defaultTtlSeconds = DEFAULT_TTL_SECONDS) {
        // makeOptionalJwt trims entries to match the Python side's get_list, so a key value like
        // "new, old" produces the same key set in both languages.
        this.jwt = makeOptionalJwt(commaSeparatedKeys || '')
        this.audience = audience
        this.defaultTtlSeconds = defaultTtlSeconds
    }

    get enabled(): boolean {
        return this.jwt !== null
    }

    /** Sign `claims` (e.g. team_id and the target entity's id) with the newest key. */
    mint(claims: object, ttlSeconds?: number): string {
        if (!this.jwt) {
            throw new Error(`Cannot mint service token for ${this.audience}: no signing key configured`)
        }
        return this.jwt.sign(claims, this.audience, { expiresIn: ttlSeconds ?? this.defaultTtlSeconds })
    }

    /** Verify signature, expiry, and audience against the full key set (rotation-safe). */
    verify(token: string): jwt.JwtPayload {
        if (!this.jwt) {
            throw new Error(`Cannot verify service token for ${this.audience}: no signing key configured`)
        }
        return this.jwt.verify(token, this.audience, {
            // Pin HS256 to match the Python minter; don't accept other HMAC variants the
            // library would otherwise allow.
            algorithms: ['HS256'],
            clockTolerance: CLOCK_TOLERANCE_SECONDS,
        }) as jwt.JwtPayload
    }
}

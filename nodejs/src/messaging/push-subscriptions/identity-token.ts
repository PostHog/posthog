import jwt from 'jsonwebtoken'

const AUDIENCE = 'posthog:push_identity'

/** ES256 only. The customer signs with an EC private key and registers the public half on the
 * channel, so PostHog never holds a key that can mint a token.
 *
 * Verification is deliberately single-algorithm. An HS256 pass alongside this one is the JWT
 * algorithm-confusion attack waiting to happen: the public key is published on the channel, so
 * anyone holding it could sign an HMAC token for any user.
 */
export function verifyPushIdentityToken(params: {
    token: string
    distinctId: string
    appId: string
    publicKeys: string[]
}): boolean {
    for (const publicKey of params.publicKeys) {
        if (decodeMatches(params.token, publicKey, params.distinctId, params.appId)) {
            return true
        }
    }
    return false
}

function decodeMatches(token: string, key: string, distinctId: string, appId: string): boolean {
    try {
        // Only the signature is checked here. The claims are checked below with PyJWT's rules, which
        // differ from jsonwebtoken's, so a token Django accepts is accepted here and nothing more.
        const payload = jwt.verify(token, key, {
            algorithms: ['ES256'],
            ignoreExpiration: true,
            ignoreNotBefore: true,
        })
        if (typeof payload !== 'object' || payload === null) {
            return false
        }
        const claims = payload as Record<string, unknown>
        return claimsValid(claims, Date.now() / 1000) && claims.sub === distinctId && claims.app_id === appId
    } catch {
        // Covers a bad signature and a key that cannot be used with ES256. Every such case fails
        // closed rather than raising.
        return false
    }
}

function claimsValid(claims: Record<string, unknown>, now: number): boolean {
    // An external signer can mint a token with no exp, so require it.
    if (claims.exp === undefined || claims.exp === null) {
        return false
    }
    for (const name of ['iat', 'nbf', 'exp']) {
        if (!(name in claims)) {
            continue
        }
        const value = pythonInt(claims[name])
        if (value === null) {
            return false
        }
        if (name === 'exp' ? value <= now : value > now) {
            return false
        }
    }
    if ('jti' in claims && typeof claims.jti !== 'string') {
        return false
    }
    const audiences = typeof claims.aud === 'string' ? [claims.aud] : claims.aud
    if (!Array.isArray(audiences) || audiences.some((audience) => typeof audience !== 'string')) {
        return false
    }
    return audiences.includes(AUDIENCE)
}

/** Python's `int()` over a JSON value, which is how PyJWT reads a time claim: a number truncates, a
 * boolean is 0 or 1, and a string must hold a whole number. Returns null where Python raises. */
function pythonInt(value: unknown): number | null {
    if (typeof value === 'boolean') {
        return value ? 1 : 0
    }
    if (typeof value === 'number') {
        return Number.isFinite(value) ? Math.trunc(value) : null
    }
    if (typeof value === 'string' && /^\s*[+-]?\d+(_\d+)*\s*$/.test(value)) {
        return Number(value.replace(/_/g, '').trim())
    }
    return null
}

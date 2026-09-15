import jwt from 'jsonwebtoken'

const AUDIENCE = 'posthog:push_identity'
const ASYMMETRIC_ALGORITHM = 'ES256'
const HMAC_ALGORITHM = 'HS256'

/** True when the token is a valid, unexpired assertion for exactly this (distinctId, appId).
 *
 * Each key type is verified under one algorithm only. Passing both would allow the JWT
 * algorithm-confusion attack, where an HS256 token is verified against a public key.
 */
export function verifyPushIdentityToken(params: {
    token: string
    distinctId: string
    appId: string
    publicKeys: string[]
    secrets: (string | null | undefined)[]
}): boolean {
    for (const publicKey of params.publicKeys) {
        if (decodeMatches(params.token, publicKey, ASYMMETRIC_ALGORITHM, params.distinctId, params.appId)) {
            return true
        }
    }
    for (const secret of params.secrets) {
        if (secret && decodeMatches(params.token, secret, HMAC_ALGORITHM, params.distinctId, params.appId)) {
            return true
        }
    }
    return false
}

function decodeMatches(token: string, key: string, algorithm: string, distinctId: string, appId: string): boolean {
    try {
        const payload = jwt.verify(token, key, {
            algorithms: [algorithm as jwt.Algorithm],
            audience: AUDIENCE,
            // An external signer can mint a token with no exp, and jsonwebtoken only checks expiry
            // when the claim is present, so require it.
            required: ['exp'],
        } as jwt.VerifyOptions)
        if (typeof payload !== 'object' || payload === null) {
            return false
        }
        const claims = payload as jwt.JwtPayload & { app_id?: unknown }
        if (typeof claims.exp !== 'number') {
            return false
        }
        return claims.sub === distinctId && claims.app_id === appId
    } catch {
        // Covers a bad signature, an expired token, and a key that cannot be used with this
        // algorithm. Every such case fails closed rather than raising.
        return false
    }
}

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
        const payload = jwt.verify(token, key, {
            algorithms: ['ES256'],
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
        // Covers a bad signature, an expired token, and a key that cannot be used with ES256.
        // Every such case fails closed rather than raising.
        return false
    }
}

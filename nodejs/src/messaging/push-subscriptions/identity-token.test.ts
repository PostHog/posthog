import { generateKeyPairSync, randomBytes } from 'crypto'
import jwt from 'jsonwebtoken'

import { verifyPushIdentityToken } from './identity-token'

describe('verifyPushIdentityToken', () => {
    const AUDIENCE = 'posthog:push_identity'
    // Generated rather than written in: a literal here trips the hardcoded-credential scan.
    const secret = randomBytes(32).toString('hex')
    const distinctId = 'user-1'
    const appId = 'com.example.app'

    const { publicKey, privateKey } = generateKeyPairSync('ec', {
        namedCurve: 'P-256',
        publicKeyEncoding: { type: 'spki', format: 'pem' },
        privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    })

    const sign = (payload: Record<string, unknown>, key: string = privateKey): string =>
        jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE, ...payload }, key, {
            algorithm: 'ES256',
            expiresIn: 300,
        })

    const verify = (token: string, overrides: Partial<Parameters<typeof verifyPushIdentityToken>[0]> = {}): boolean =>
        verifyPushIdentityToken({ token, distinctId, appId, publicKeys: [publicKey], ...overrides })

    it('accepts a token signed with the registered public key', () => {
        expect(verify(sign({}))).toEqual(true)
    })

    it('refuses an HS256 token keyed with the public key', () => {
        // Guards against reintroducing an HMAC pass. The public key is published on the channel, so
        // verifying it as an HMAC secret would let anyone holding it mint a token for any user.
        const forged = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, publicKey, {
            algorithm: 'HS256',
            expiresIn: 300,
        })

        expect(verify(forged)).toEqual(false)
    })

    it('refuses a token signed with the project secret, which is no longer accepted', () => {
        const hmac = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, secret, {
            algorithm: 'HS256',
            expiresIn: 300,
        })

        expect(verify(hmac)).toEqual(false)
    })

    it('refuses an unsigned token', () => {
        // An alg=none token has no key by definition, and the empty key is what makes this the
        // attack the test covers.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const unsigned = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, '', {
            algorithm: 'none',
            expiresIn: 300,
        } as jwt.SignOptions)

        expect(verify(unsigned)).toEqual(false)
    })

    it('refuses a token with no expiry', () => {
        // jsonwebtoken only checks expiry when the claim is present, so an external signer could
        // otherwise mint a token that never stops working.
        const forever = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, privateKey, {
            algorithm: 'ES256',
        })

        expect(verify(forever)).toEqual(false)
    })

    it('refuses an expired token', () => {
        const expired = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, privateKey, {
            algorithm: 'ES256',
            expiresIn: -10,
        })

        expect(verify(expired)).toEqual(false)
    })

    it.each([
        ['another user', { sub: 'someone-else' }],
        ['another app', { app_id: 'com.other.app' }],
        ['another audience', { aud: 'posthog:something_else' }],
    ])('refuses a token minted for %s', (_name, overrides) => {
        expect(verify(sign(overrides))).toEqual(false)
    })

    it.each([
        ['an empty string', ''],
        ['a value that is not a token', 'not-a-jwt'],
        [
            'a token with a mangled signature',
            `${jwt.sign({ sub: distinctId }, privateKey, { algorithm: 'ES256' })}tampered`,
        ],
    ])('refuses %s without raising', (_name, token) => {
        expect(verify(token)).toEqual(false)
    })

    // Django verifies with PyJWT, whose claim rules differ from jsonwebtoken's. A string payload skips
    // jsonwebtoken's own claim validation when signing, so these shapes can be minted at all.
    const now = Math.floor(Date.now() / 1000)
    it.each([
        ['exp as a whole-number string', { exp: String(now + 300) }, true],
        ['nbf as a whole-number string in the past', { exp: now + 300, nbf: String(now - 10) }, true],
        ['exp as a fractional string', { exp: `${now + 300}.5` }, false],
        ['iat in the future', { exp: now + 300, iat: now + 600 }, false],
        ['iat that is not a number', { exp: now + 300, iat: 'yesterday' }, false],
        ['iat as null', { exp: now + 300, iat: null }, false],
        ['an audience list holding a non-string', { exp: now + 300, aud: [AUDIENCE, 5] }, false],
        ['a numeric jti', { exp: now + 300, jti: 7 }, false],
    ])('matches django for %s', (_name, claims, accepted) => {
        const token = jwt.sign(
            JSON.stringify({ sub: distinctId, app_id: appId, aud: AUDIENCE, ...claims }),
            privateKey,
            {
                algorithm: 'ES256',
            }
        )

        expect(verify(token)).toEqual(accepted)
    })

    it('refuses everything when the channel registered no key', () => {
        expect(verify(sign({}), { publicKeys: [] })).toEqual(false)
    })
})

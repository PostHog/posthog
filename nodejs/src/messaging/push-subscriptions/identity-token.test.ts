import { generateKeyPairSync } from 'crypto'
import jwt from 'jsonwebtoken'

import { verifyPushIdentityToken } from './identity-token'

describe('verifyPushIdentityToken', () => {
    const AUDIENCE = 'posthog:push_identity'
    const secret = 'phx_secret_api_token'
    const distinctId = 'user-1'
    const appId = 'com.example.app'

    const { publicKey, privateKey } = generateKeyPairSync('ec', {
        namedCurve: 'P-256',
        publicKeyEncoding: { type: 'spki', format: 'pem' },
        privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    })

    const sign = (
        payload: Record<string, unknown>,
        key: string = secret,
        options: jwt.SignOptions = { algorithm: 'HS256' }
    ): string =>
        jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE, ...payload }, key, { expiresIn: 300, ...options })

    const verify = (token: string, overrides: Partial<Parameters<typeof verifyPushIdentityToken>[0]> = {}): boolean =>
        verifyPushIdentityToken({ token, distinctId, appId, publicKeys: [publicKey], secrets: [secret], ...overrides })

    it('accepts a token the customer backend signed with the shared secret', () => {
        expect(verify(sign({}))).toEqual(true)
    })

    it('accepts a token signed with the registered public key', () => {
        expect(verify(sign({}, privateKey, { algorithm: 'ES256' }))).toEqual(true)
    })

    it('accepts a token signed with the backup secret while a rotation is in flight', () => {
        // Rejecting during rotation would fail every in-flight registration for a project.
        const token = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, 'rotated-secret', {
            algorithm: 'HS256',
            expiresIn: 300,
        })

        expect(verify(token, { secrets: [secret, 'rotated-secret'] })).toEqual(true)
    })

    it('refuses an HS256 token keyed with the public key', () => {
        // The classic JWT algorithm-confusion attack: the public key is published on the channel, so
        // verifying it as an HMAC secret would let anyone holding it mint a token for any user.
        const forged = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, publicKey, {
            algorithm: 'HS256',
            expiresIn: 300,
        })

        expect(verify(forged)).toEqual(false)
    })

    it('refuses an unsigned token', () => {
        const unsigned = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, '', {
            algorithm: 'none',
            expiresIn: 300,
        } as jwt.SignOptions)

        expect(verify(unsigned)).toEqual(false)
    })

    it('refuses a token with no expiry', () => {
        // jsonwebtoken only checks expiry when the claim is present, so an external signer could
        // otherwise mint a token that never stops working.
        const forever = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, secret, { algorithm: 'HS256' })

        expect(verify(forever)).toEqual(false)
    })

    it('refuses an expired token', () => {
        const expired = jwt.sign({ sub: distinctId, app_id: appId, aud: AUDIENCE }, secret, {
            algorithm: 'HS256',
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
        ['a token with a mangled signature', `${jwt.sign({ sub: distinctId }, secret)}tampered`],
    ])('refuses %s without raising', (_name, token) => {
        expect(verify(token)).toEqual(false)
    })

    it('refuses everything when the channel registered no keys at all', () => {
        expect(verify(sign({}), { publicKeys: [], secrets: [] })).toEqual(false)
    })

    it('ignores a null secret rather than treating it as a key', () => {
        expect(verify(sign({}), { publicKeys: [], secrets: [null, undefined] })).toEqual(false)
    })
})

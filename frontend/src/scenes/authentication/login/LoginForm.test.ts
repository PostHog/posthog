import { buildLoginSupportMessage, precheckConfirmsAccount } from './LoginForm'
import { PrecheckResponseType } from './loginLogic'

function precheck(overrides: Partial<PrecheckResponseType> = {}): PrecheckResponseType {
    return { status: 'completed', saml_available: false, email: 'user@example.com', ...overrides }
}

describe('LoginForm support message', () => {
    // The precheck answers password_login_available:true for an unknown email to block enumeration,
    // so a password-only precheck must NOT count as a confirmed account.
    it.each<[string, Partial<PrecheckResponseType>, boolean]>([
        ['password available only (unknown email looks the same)', { password_login_available: true }, false],
        ['known passwordless account', { password_login_available: false }, true],
        ['linked social identity', { social_providers: ['google-oauth2'] }, true],
        ['registered passkey', { webauthn_credentials: [{ id: 'x', type: 'public-key' } as any] }, true],
        ['domain SAML only, no account data', { saml_available: true }, false],
    ])('precheckConfirmsAccount: %s', (_name, overrides, expected) => {
        expect(precheckConfirmsAccount(precheck(overrides))).toBe(expected)
    })

    it('reports the password method as shown, not available, when no account is confirmed', () => {
        const message = buildLoginSupportMessage({
            errorCode: 'invalid_credentials',
            availableLoginMethods: ['password'],
            precheckTrusted: true,
            precheckConfirmedAccount: false,
            codeVerificationPending: false,
        })
        expect(message).toContain('Login options shown: password')
        expect(message).not.toContain('Login methods available')
    })

    it('reports methods as available once the account is confirmed', () => {
        const message = buildLoginSupportMessage({
            errorCode: 'invalid_credentials',
            availableLoginMethods: ['password', 'google-oauth2'],
            precheckTrusted: true,
            precheckConfirmedAccount: true,
            codeVerificationPending: false,
        })
        expect(message).toContain('Login methods available: password, Google')
    })

    it('states no methods when the precheck is not trusted', () => {
        const message = buildLoginSupportMessage({
            errorCode: 'invalid_credentials',
            availableLoginMethods: ['password'],
            precheckTrusted: false,
            precheckConfirmedAccount: false,
            codeVerificationPending: false,
        })
        expect(message).not.toContain('Login options shown')
        expect(message).not.toContain('Login methods available')
    })
})

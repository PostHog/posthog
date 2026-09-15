import { Region } from '~/types'

import { buildLoginSupportContext } from './loginSupportContext'

describe('buildLoginSupportContext', () => {
    const base = {
        errorCode: 'invalid_credentials',
        region: Region.US,
        confirmedLoginMethods: [],
        passwordLoginUnavailable: false,
        precheckTrusted: true,
        codeVerificationPending: false,
    }

    it('carries the error code and the region', () => {
        const context = buildLoginSupportContext(base)
        expect(context).toContain('Error code: invalid_credentials')
        expect(context).toContain('Data region: US')
    })

    it.each([
        [
            'nothing is confirmed',
            { confirmedLoginMethods: [] },
            'Login methods: none confirmed. The account check cannot tell a password-only account from an email with no account.',
        ],
        [
            'the account is known to have no usable password and nothing else',
            { confirmedLoginMethods: [], passwordLoginUnavailable: true },
            'Login methods: none. The account has no usable password, and the check found no other method.',
        ],
        [
            'the account has a passkey and a linked provider',
            { confirmedLoginMethods: ['passkey' as const, 'google-oauth2' as const] },
            'Login methods confirmed: passkey, Google',
        ],
        [
            'the precheck did not resolve for this email',
            { precheckTrusted: false },
            'Login methods: unknown, the account check did not complete',
        ],
        [
            'the domain enforces SSO',
            { ssoEnforcement: 'google-oauth2' as const },
            'Login method: SSO enforced (Google)',
        ],
        [
            'an enforced provider is left over from a precheck for another email',
            { ssoEnforcement: 'google-oauth2' as const, precheckTrusted: false },
            'Login methods: unknown, the account check did not complete',
        ],
    ])('states what it knows about the login methods when %s', (_case, overrides, expected) => {
        expect(buildLoginSupportContext({ ...base, ...overrides })).toContain(expected)
    })
})

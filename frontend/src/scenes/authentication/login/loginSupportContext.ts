import { SSO_PROVIDER_NAMES } from 'lib/constants'

import { LoginMethod, Region, SSOProvider } from '~/types'

function loginMethodLabel(method: LoginMethod): string {
    if (method === 'passkey') {
        return 'passkey'
    }
    return method && method !== 'password' ? SSO_PROVIDER_NAMES[method] : ''
}

// The facts support triages a login ticket on: the error code, the region, and the methods the
// account can log in with. The block travels as machine context rather than as message text, so
// nobody can type over it, and it states only what the login precheck can prove.
export function buildLoginSupportContext({
    errorCode,
    region,
    ssoEnforcement,
    confirmedLoginMethods,
    precheckTrusted,
    codeVerificationPending,
}: {
    errorCode?: string
    region?: Region | null
    ssoEnforcement?: SSOProvider | null
    confirmedLoginMethods: LoginMethod[]
    precheckTrusted: boolean
    codeVerificationPending: boolean
}): string {
    const lines = ['Login error details, collected by PostHog:']
    if (errorCode) {
        lines.push(`Error code: ${errorCode}`)
    }
    if (region) {
        lines.push(`Data region: ${region}`)
    }
    if (ssoEnforcement) {
        lines.push(`Login method: SSO enforced (${SSO_PROVIDER_NAMES[ssoEnforcement]})`)
    } else if (!precheckTrusted) {
        // A failed precheck reports permissive defaults, and a stale one still describes the
        // previous email's account.
        lines.push('Login methods: unknown, the account check did not complete')
    } else {
        const labels = confirmedLoginMethods.map(loginMethodLabel).filter(Boolean)
        lines.push(
            labels.length
                ? `Login methods confirmed: ${labels.join(', ')}`
                : 'Login methods: none confirmed. The account check cannot tell a password-only account from an email with no account.'
        )
    }
    if (codeVerificationPending) {
        lines.push('Waiting on an emailed verification code.')
    }
    return lines.join('\n')
}

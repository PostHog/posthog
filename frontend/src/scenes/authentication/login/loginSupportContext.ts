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
    passwordLoginUnavailable,
    precheckTrusted,
    codeVerificationPending,
}: {
    errorCode?: string
    region?: Region | null
    ssoEnforcement?: SSOProvider | null
    confirmedLoginMethods: LoginMethod[]
    passwordLoginUnavailable: boolean
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
    if (!precheckTrusted) {
        // A failed precheck reports permissive defaults, and a stale one still describes the
        // previous email's account. `sso_enforcement` is read from that same response, so the
        // trust gate has to come first or a stale provider is reported as fact for a new address.
        lines.push('Login methods: unknown, the account check did not complete')
    } else if (ssoEnforcement) {
        lines.push(`Login method: SSO enforced (${SSO_PROVIDER_NAMES[ssoEnforcement]})`)
    } else {
        const labels = confirmedLoginMethods.map(loginMethodLabel).filter(Boolean)
        if (labels.length) {
            lines.push(`Login methods confirmed: ${labels.join(', ')}`)
        } else if (passwordLoginUnavailable) {
            // The precheck reports the password as unusable only for an account it found, so this
            // dead end is proven and must not get the ambiguous wording below.
            lines.push('Login methods: none. The account has no usable password, and the check found no other method.')
        } else {
            lines.push(
                'Login methods: none confirmed. The account check cannot tell a password-only account from an email with no account.'
            )
        }
    }
    if (codeVerificationPending) {
        lines.push('Waiting on an emailed verification code.')
    }
    return lines.join('\n')
}

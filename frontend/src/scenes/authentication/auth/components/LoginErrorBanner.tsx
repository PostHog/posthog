import { useActions, useValues } from 'kea'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'

import { LoginMethod, Region, SSOProvider } from '~/types'

import { loginLogic } from '../loginLogic'

function loginMethodLabel(method: LoginMethod): string {
    if (method === 'password') {
        return 'password'
    }
    if (method === 'passkey') {
        return 'passkey'
    }
    return method ? SSO_PROVIDER_NAMES[method] : ''
}

// The support form starts empty for the person, so a login-error ticket loses the context the page
// already holds. Prefill the message with the error code, region, and login methods, so support can
// triage without a round trip.
function buildLoginSupportMessage({
    errorCode,
    region,
    ssoEnforcement,
    availableLoginMethods,
    precheckTrusted,
    codeVerificationPending,
}: {
    errorCode?: string
    region?: Region | null
    ssoEnforcement?: SSOProvider | null
    availableLoginMethods: LoginMethod[]
    precheckTrusted: boolean
    codeVerificationPending: boolean
}): string {
    const lines = ['I need help logging in.']
    if (errorCode) {
        lines.push(`Error code: ${errorCode}`)
    }
    if (region) {
        lines.push(`Data region: ${region}`)
    }
    // Only state the account's methods when the precheck is trustworthy. A failed or stale one
    // reports permissive defaults (e.g. password login for an SSO-only account), which would point
    // support the wrong way.
    if (precheckTrusted) {
        if (ssoEnforcement) {
            lines.push(`Login method: SSO enforced (${SSO_PROVIDER_NAMES[ssoEnforcement]})`)
        } else {
            const labels = availableLoginMethods.map(loginMethodLabel).filter(Boolean)
            if (labels.length) {
                lines.push(`Login methods available: ${labels.join(', ')}`)
            }
        }
    }
    if (codeVerificationPending) {
        lines.push('Waiting on an emailed verification code.')
    }
    return lines.join('\n')
}

/** The login error that `loginLogic` holds, from a rejected password or from a sign-in that the server
 * redirected back with `?error_code=`. The email step shows it too, because a failed SSO or social
 * sign-in lands there. */
export function LoginErrorBanner(): JSX.Element | null {
    const { generalError, precheckResponse, login, availableLoginMethods, codeVerificationRequired } =
        useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { sendSupportRequest } = useValues(supportLogic)

    if (!generalError) {
        return null
    }

    return (
        <AuthBanner variant="danger" className="mb-4">
            <span>
                {generalError.detail ||
                    ERROR_MESSAGES[generalError.code] ||
                    'Could not complete your login. Please try again.'}
            </span>
            {preflight?.cloud && (
                <>
                    {' '}
                    <Link
                        data-attr="login-error-contact-support"
                        onClick={(e) => {
                            e.preventDefault()
                            // Trust the precheck only when it resolved for the email now
                            // in the form: a failed precheck reports permissive defaults,
                            // and a stale one still holds the previous email's account.
                            const precheckTrusted =
                                precheckResponse.status === 'completed' &&
                                !precheckResponse.precheckFailed &&
                                precheckResponse.email === login.email
                            openSupportForm({
                                kind: 'support',
                                email: login.email,
                                // Prefill only into an empty form. Passing no message lets
                                // openSupportForm keep a draft the person already started,
                                // so reopening this link never overwrites their text.
                                message: sendSupportRequest.message
                                    ? undefined
                                    : buildLoginSupportMessage({
                                          errorCode: generalError.code,
                                          region: preflight?.region,
                                          ssoEnforcement: precheckResponse.sso_enforcement,
                                          availableLoginMethods,
                                          precheckTrusted,
                                          codeVerificationPending: codeVerificationRequired,
                                      }),
                            })
                        }}
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                    >
                        Need help?
                    </Link>
                </>
            )}
        </AuthBanner>
    )
}

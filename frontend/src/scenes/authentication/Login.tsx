import './Login.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSOEnforcedLoginButton, SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { isEmail } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { LoginMethod } from '~/types'

import { RedirectIfLoggedInOtherInstance } from './RedirectToLoggedInInstance'
import RegionSelect from './RegionSelect'
import { SupportModalButton } from './SupportModalButton'
import { loginLogic } from './loginLogic'

export const ERROR_MESSAGES: Record<string, string | JSX.Element> = {
    no_new_organizations:
        'Your email address is not associated with an account. Please ask your administrator for an invite.',
    invalid_sso_provider: (
        <>
            The SSO provider you specified is invalid. Visit{' '}
            <Link to="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </Link>{' '}
            for details.
        </>
    ),
    improperly_configured_sso: (
        <>
            Cannot login with SSO provider because the provider is not configured, or your instance does not have the
            required license. Please visit{' '}
            <Link to="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </Link>{' '}
            for details.
        </>
    ),
    jit_not_enabled:
        'We could not find an account with your email address and your organization does not support automatic enrollment. Please contact your administrator for an invite.',
    saml_sso_enforced:
        'Your organization requires SAML SSO authentication. Please enter your email address to access your account.',
    google_sso_enforced: 'Your organization does not allow this authentication method. Please log in with Google.',
    github_sso_enforced: 'Your organization does not allow this authentication method. Please log in with GitHub.',
    gitlab_sso_enforced: 'Your organization does not allow this authentication method. Please log in with GitLab.',
    // our catch-all case, so the message is generic
    sso_enforced: "Please log in with your organization's required SSO method.",
    oauth_cancelled: "Sign in was cancelled. Please try again when you're ready.",
}

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

export function Login(): JSX.Element {
    const { precheck, resendEmailMFA, clearGeneralError, resetLogin } = useActions(loginLogic)
    const { openSupportForm } = useActions(supportLogic)
    const {
        precheckResponse,
        precheckResponseLoading,
        login,
        isLoginSubmitting,
        generalError,
        signupUrl,
        resendResponseLoading,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const passwordInputRef = useRef<HTMLInputElement>(null)
    const preventPasswordError = useRef(false)
    const isPasswordHidden = precheckResponse.status === 'pending' || precheckResponse.sso_enforcement
    const isEmailVerificationSent = generalError?.code === 'email_verification_sent'
    const wasPasswordHiddenRef = useRef(isPasswordHidden)

    const lastLoginMethod = getCookie(LAST_LOGIN_METHOD_COOKIE) as LoginMethod
    const prevEmail = usePrevious(login.email)

    useEffect(() => {
        const wasPasswordHidden = wasPasswordHiddenRef.current
        wasPasswordHiddenRef.current = isPasswordHidden

        if (!isPasswordHidden) {
            passwordInputRef.current?.focus()
        } else if (!wasPasswordHidden) {
            // clear form when transitioning from visible to hidden
            resetLogin()
        }
    }, [isPasswordHidden, resetLogin])

    // Trigger precheck for password manager autofill/paste (detected by large character delta)
    useEffect(() => {
        const charDelta = login.email.length - (prevEmail?.length ?? 0)
        const isAutofill = charDelta > 1

        if (isAutofill && isEmail(login.email, { requireTLD: true }) && precheckResponse.status === 'pending') {
            precheck({ email: login.email })
        }
    }, [login.email, prevEmail, precheckResponse.status, precheck])

    return (
        <BridgePage
            view="login"
            hedgehog
            message={
                <>
                    Welcome to
                    <br /> PostHog{preflight?.cloud ? ' Cloud' : ''}!
                </>
            }
            footer={<SupportModalButton />}
        >
            {preflight?.cloud && <RedirectIfLoggedInOtherInstance />}
            <div className="deprecated-space-y-4">
                <h2>{isEmailVerificationSent ? 'Check your email' : 'Log in'}</h2>
                {generalError && (
                    <LemonBanner type={generalError.code === 'email_verification_sent' ? 'warning' : 'error'}>
                        <>
                            {generalError.detail || ERROR_MESSAGES[generalError.code] || (
                                <>
                                    Could not complete your login.
                                    <br />
                                    Please try again.
                                </>
                            )}
                            {preflight?.cloud && (
                                <>
                                    {' '}
                                    <Link
                                        data-attr="login-error-contact-support"
                                        onClick={(e) => {
                                            e.preventDefault()
                                            openSupportForm({
                                                kind: 'support',
                                                target_area: 'login',
                                                email: login.email,
                                            })
                                        }}
                                    >
                                        Need help?
                                    </Link>
                                </>
                            )}
                        </>
                    </LemonBanner>
                )}
                {isEmailVerificationSent ? (
                    <div className="deprecated-space-y-4">
                        <div className="flex justify-center">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                loading={resendResponseLoading}
                                onClick={() => resendEmailMFA(null)}
                            >
                                Resend verification email
                            </LemonButton>
                        </div>
                        <div className="text-center">
                            <Link onClick={() => clearGeneralError()} className="text-muted">
                                Back to login
                            </Link>
                        </div>
                    </div>
                ) : (
                    <Form
                        logic={loginLogic}
                        formKey="login"
                        enableFormOnSubmit
                        onSubmitCapture={(e) => {
                            if (isPasswordHidden || preventPasswordError.current) {
                                e.preventDefault()
                                e.stopPropagation()
                                preventPasswordError.current = false
                            }
                        }}
                        className="deprecated-space-y-4"
                    >
                        <RegionSelect />
                        <LemonField name="email" label="Email">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus
                                data-attr="login-email"
                                placeholder="email@yourcompany.com"
                                type="email"
                                onBlur={() => precheck({ email: login.email })}
                                onPressEnter={(e) => {
                                    if (isPasswordHidden) {
                                        e.preventDefault() // Don't trigger submission if password field is still hidden
                                        passwordInputRef.current?.focus()
                                    }
                                }}
                                badgeText={lastLoginMethod === 'password' ? 'Last used' : undefined}
                            />
                        </LemonField>
                        <div className={clsx('PasswordWrapper', isPasswordHidden && 'zero-height')}>
                            <LemonField
                                name="password"
                                label={
                                    <div className="flex flex-1 items-center justify-between gap-2">
                                        <span>Password</span>
                                        <Link
                                            to={[urls.passwordReset(), { email: login.email }]}
                                            data-attr="forgot-password"
                                            tabIndex={-1}
                                        >
                                            Forgot your password?
                                        </Link>
                                    </div>
                                }
                            >
                                <LemonInput
                                    type="password"
                                    inputRef={passwordInputRef}
                                    className="ph-ignore-input"
                                    data-attr="password"
                                    placeholder="••••••••••"
                                    autoComplete="current-password"
                                />
                            </LemonField>
                        </div>

                        {/* Show regular login button if SSO is not enforced */}
                        {!precheckResponse.sso_enforcement && (
                            <LemonButton
                                type="primary"
                                status="alt"
                                htmlType="submit"
                                data-attr="password-login"
                                fullWidth
                                center
                                loading={isLoginSubmitting || precheckResponseLoading}
                                size="large"
                                onMouseDown={() => {
                                    if (isPasswordHidden) {
                                        // prevent empty password error
                                        preventPasswordError.current = true
                                    }
                                }}
                            >
                                Log in
                            </LemonButton>
                        )}

                        {/* Show enforced SSO button if required */}
                        {precheckResponse.sso_enforcement && (
                            <SSOEnforcedLoginButton
                                provider={precheckResponse.sso_enforcement}
                                email={login.email}
                                isLastUsed={lastLoginMethod === precheckResponse.sso_enforcement}
                            />
                        )}

                        {/* Show optional SAML SSO button if available */}
                        {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                            <SSOEnforcedLoginButton
                                provider="saml"
                                email={login.email}
                                isLastUsed={lastLoginMethod === 'saml'}
                            />
                        )}
                    </Form>
                )}
                {!isEmailVerificationSent && preflight?.cloud && (
                    <div className="text-center mt-4">
                        Don't have an account?{' '}
                        <Link to={[signupUrl, { email: login.email }]} data-attr="signup" className="font-bold">
                            Create an account
                        </Link>
                    </div>
                )}
                {!isEmailVerificationSent && !precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                    <SocialLoginButtons
                        caption="Or log in with"
                        topDivider
                        lastUsedProvider={lastLoginMethod}
                        showPasskey
                    />
                )}
            </div>
        </BridgePage>
    )
}

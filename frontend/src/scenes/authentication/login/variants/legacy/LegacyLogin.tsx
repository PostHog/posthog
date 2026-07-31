import '../../Login.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSOEnforcedLoginButton, SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { Skeleton } from 'lib/ui/quill'
import { isWebKitBrowser } from 'lib/utils/dom'
import { isEmail } from 'lib/utils/url'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import { OtherRegionHint } from 'scenes/authentication/shared/OtherRegionHint'
import { RedirectIfLoggedInOtherInstance } from 'scenes/authentication/shared/RedirectToLoggedInInstance'
import RegionSelect from 'scenes/authentication/shared/RegionSelect'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { LoginMethod } from '~/types'

import { loginLogic } from '../../loginLogic'
import { SessionRiskBanner } from '../../SessionRiskBanner'

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

function Login(): JSX.Element {
    const { precheck, resendCodeBasedVerification, exitCodeVerification, resetLogin, devLogin, loadDevUsers } =
        useActions(loginLogic)
    const { openSupportForm } = useActions(supportLogic)
    const {
        precheckResponse,
        precheckResponseLoading,
        login,
        isLoginSubmitting,
        generalError,
        signupUrl,
        resendResponseLoading,
        codeVerificationRequired,
        isCodeVerificationSubmitting,
        devUsers,
        devUsersLoading,
        devLoginTimeSavedLabel,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)
    const allowDevLogin = !!preflight?.allow_dev_login

    useEffect(() => {
        if (allowDevLogin) {
            loadDevUsers(null)
        }
    }, [allowDevLogin, loadDevUsers])

    const passwordInputRef = useRef<HTMLInputElement>(null)
    const preventPasswordError = useRef(false)
    const isPasswordHidden = precheckResponse.status === 'pending' || precheckResponse.sso_enforcement
    const isCodeSent = codeVerificationRequired
    const loginTitle = isCodeSent ? 'Enter your login code' : 'Log in'
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
        <BridgePage view="login" footer={<SupportModalButton />}>
            {preflight?.cloud && <RedirectIfLoggedInOtherInstance />}
            <div className="deprecated-space-y-4">
                <h2>{loginTitle}</h2>
                <SessionRiskBanner />
                {generalError && (
                    <LemonBanner type={generalError.code === 'code_based_verification_sent' ? 'warning' : 'error'}>
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
                {generalError?.code === 'invalid_credentials' && <OtherRegionHint />}
                {isCodeSent ? (
                    <Form
                        logic={loginLogic}
                        formKey="codeVerification"
                        enableFormOnSubmit
                        className="deprecated-space-y-4"
                    >
                        <LemonField name="code" label="Verification code">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus
                                data-attr="code-verification"
                                placeholder="123456"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            status="alt"
                            htmlType="submit"
                            data-attr="code-verification-submit"
                            fullWidth
                            center
                            size="large"
                            loading={isCodeVerificationSubmitting}
                        >
                            Verify and log in
                        </LemonButton>
                        <div className="flex justify-center">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                loading={resendResponseLoading}
                                onClick={() => resendCodeBasedVerification(null)}
                            >
                                Resend code
                            </LemonButton>
                        </div>
                        <div className="text-center">
                            <Link onClick={() => exitCodeVerification()} className="text-muted">
                                Back to login
                            </Link>
                        </div>
                    </Form>
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
                                // The `webauthn` token enables passkey autofill (conditional UI), which
                                // we only offer on WebKit; elsewhere the auto-modal handles passkeys.
                                autoComplete={isWebKitBrowser() ? 'username webauthn' : undefined}
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
                {!isCodeSent && preflight?.cloud && (
                    <div className="text-center mt-4">
                        Don't have an account?{' '}
                        <Link to={[signupUrl, { email: login.email }]} data-attr="signup" className="font-bold">
                            Create an account
                        </Link>
                    </div>
                )}
                {!isCodeSent && !precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                    <SocialLoginButtons
                        caption="Or log in with"
                        topDivider
                        lastUsedProvider={lastLoginMethod}
                        showPasskey
                    />
                )}
                {allowDevLogin && (
                    <div className="deprecated-space-y-2 border-t border-dashed pt-4 mt-4">
                        <div className="flex items-center justify-between">
                            <h4 className="m-0">Dev login</h4>
                        </div>
                        <p className="text-muted text-sm m-0">
                            Click a user to log in without a password. This list is only exposed in development mode.
                        </p>
                        {!devUsersLoading && devLoginTimeSavedLabel && (
                            <p className="text-muted text-sm m-0">{devLoginTimeSavedLabel}</p>
                        )}
                        {devUsersLoading && <Skeleton className="w-full h-10" />}
                        <div className="deprecated-space-y-1">
                            {devUsers.map((u) => (
                                <LemonButton
                                    key={u.email}
                                    type="secondary"
                                    fullWidth
                                    data-attr={`dev-login-${u.email}`}
                                    onClick={() => devLogin(u.email)}
                                >
                                    <span className="flex items-center gap-2 w-full">
                                        <span className="flex-1 text-left truncate">{u.email}</span>
                                        {u.label && (
                                            <LemonTag type="success" size="small">
                                                {u.label}
                                            </LemonTag>
                                        )}
                                        {u.is_staff && !u.label && (
                                            <LemonTag type="default" size="small">
                                                Staff
                                            </LemonTag>
                                        )}
                                    </span>
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </BridgePage>
    )
}

export { Login as LegacyLogin }

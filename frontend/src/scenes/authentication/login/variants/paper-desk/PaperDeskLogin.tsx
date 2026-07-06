import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

import { IconCheckCircle } from '@posthog/icons'

import { getCookie } from 'lib/api'
import { SocialLoginButtons, SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { isWebKitBrowser } from 'lib/utils/dom'
import { isEmail } from 'lib/utils/url'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import { OtherRegionHint } from 'scenes/authentication/shared/OtherRegionHint'
import { CardTitle } from 'scenes/authentication/shared/paperDesk/CardTitle'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { RegionField } from 'scenes/authentication/shared/paperDesk/RegionField'
import { RedirectIfLoggedInOtherInstance } from 'scenes/authentication/shared/RedirectToLoggedInInstance'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { LoginMethod } from '~/types'

import { loginLogic } from '../../loginLogic'

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

function Login(): JSX.Element {
    const { precheck, clearGeneralError, resendEmailMFA } = useActions(loginLogic)
    const { openSupportForm } = useActions(supportLogic)
    const {
        precheckResponse,
        precheckResponseLoading,
        login,
        isLoginSubmitting,
        generalError,
        signupUrl,
        resendResponseLoading,
        resendResponse,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const isPasswordHidden = !!precheckResponse.sso_enforcement
    const isEmailVerificationSent = generalError?.code === 'email_verification_sent'
    const lastLoginMethod = getCookie(LAST_LOGIN_METHOD_COOKIE) as LoginMethod
    const prevEmail = usePrevious(login.email)

    useEffect(() => {
        const charDelta = login.email.length - (prevEmail?.length ?? 0)
        const isAutofill = charDelta > 1

        if (isAutofill && isEmail(login.email, { requireTLD: true }) && precheckResponse.status === 'pending') {
            precheck({ email: login.email })
        }
    }, [login.email, prevEmail, precheckResponse.status, precheck])

    const footer = (
        <p className="mt-5 mb-0 text-sm text-secondary text-center">
            New to PostHog?{' '}
            <Link
                to={[signupUrl, { email: login.email }]}
                data-attr="signup"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                Create an account →
            </Link>
        </p>
    )

    return (
        <PaperDeskScene notes={['// welcome back', '// 500,000+ teams ship here']}>
            {preflight?.cloud && <RedirectIfLoggedInOtherInstance />}
            <PaperDeskCard footer={footer}>
                <CardTitle
                    title={isEmailVerificationSent ? 'Check your email' : 'Log in to PostHog'}
                    sub={isEmailVerificationSent ? undefined : "Welcome back. Let's go ship something."}
                />
                {generalError && (
                    <div
                        className={twMerge(
                            'mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded',
                            isEmailVerificationSent
                                ? 'bg-success-highlight border-success'
                                : 'bg-danger-highlight border-danger'
                        )}
                    >
                        {generalError.detail ||
                            ERROR_MESSAGES[generalError.code] ||
                            'Could not complete your login. Please try again.'}
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
                                    className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                                >
                                    Need help?
                                </Link>
                            </>
                        )}
                    </div>
                )}
                {generalError?.code === 'invalid_credentials' && (
                    <div className="mb-4">
                        <OtherRegionHint />
                    </div>
                )}
                {isEmailVerificationSent ? (
                    <div className="flex flex-col items-center gap-3">
                        <LemonButton
                            size="large"
                            type="secondary"
                            center
                            fullWidth
                            disabled={resendResponseLoading}
                            loading={resendResponseLoading}
                            onClick={() => resendEmailMFA(null)}
                        >
                            Resend verification email
                        </LemonButton>
                        {resendResponse?.success && (
                            <p className="flex items-center gap-1 text-success mb-0" role="status">
                                <IconCheckCircle />
                                Verification email sent — check your inbox.
                            </p>
                        )}
                        <Link
                            onClick={() => clearGeneralError()}
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary"
                        >
                            Back to login
                        </Link>
                    </div>
                ) : (
                    <Form logic={loginLogic} formKey="login" enableFormOnSubmit className="flex flex-col gap-4">
                        <RegionField />
                        <LemonField name="email" label="Email">
                            {({ value, onChange, error, id }) => (
                                <LemonInput
                                    id={id}
                                    className="ph-ignore-input"
                                    data-attr="login-email"
                                    type="email"
                                    autoFocus
                                    placeholder="you@yourcompany.com"
                                    // The `webauthn` token enables passkey autofill (conditional UI),
                                    // which we only offer on WebKit; elsewhere the auto-modal handles passkeys.
                                    autoComplete={isWebKitBrowser() ? 'username webauthn' : 'email'}
                                    value={value ?? ''}
                                    onChange={onChange}
                                    onBlur={() => precheck({ email: login.email })}
                                    status={error ? 'danger' : 'default'}
                                    fullWidth
                                />
                            )}
                        </LemonField>
                        {!isPasswordHidden && (
                            <LemonField
                                name="password"
                                label={
                                    <div className="flex items-baseline justify-between w-full">
                                        <span>Password</span>
                                        <Link
                                            to={[urls.passwordReset(), { email: login.email }]}
                                            data-attr="forgot-password"
                                            className="text-xs font-semibold text-warning"
                                            tabIndex={-1}
                                        >
                                            Forgot password?
                                        </Link>
                                    </div>
                                }
                            >
                                {({ value, onChange, error, id }) => (
                                    <LemonInput
                                        id={id}
                                        className="ph-ignore-input"
                                        data-attr="password"
                                        type="password"
                                        placeholder="••••••••••"
                                        autoComplete="current-password"
                                        value={value ?? ''}
                                        onChange={onChange}
                                        status={error ? 'danger' : 'default'}
                                        fullWidth
                                    />
                                )}
                            </LemonField>
                        )}
                        {!precheckResponse.sso_enforcement && (
                            <LemonButton
                                type="primary"
                                size="large"
                                center
                                fullWidth
                                htmlType="submit"
                                data-attr="password-login"
                                loading={isLoginSubmitting || precheckResponseLoading}
                            >
                                Log in
                            </LemonButton>
                        )}
                        {precheckResponse.sso_enforcement && (
                            <SSOEnforcedLoginButton
                                provider={precheckResponse.sso_enforcement}
                                email={login.email}
                                isLastUsed={lastLoginMethod === precheckResponse.sso_enforcement}
                            />
                        )}
                        {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                            <SSOEnforcedLoginButton
                                provider="saml"
                                email={login.email}
                                isLastUsed={lastLoginMethod === 'saml'}
                            />
                        )}
                    </Form>
                )}
                {!isEmailVerificationSent && !precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                    <SocialLoginButtons
                        topDivider
                        caption="Or log in with"
                        captionLocation="top"
                        lastUsedProvider={lastLoginMethod}
                        showPasskey
                    />
                )}
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

export { Login as PaperDeskLogin }

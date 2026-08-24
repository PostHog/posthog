import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

import { IconCheckCircle } from '@posthog/icons'

import { getCookie } from 'lib/api'
import { SocialLoginButtons, SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { isWebKitBrowser } from 'lib/utils/dom'
import { isEmail } from 'lib/utils/url'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { RegionField } from 'scenes/authentication/shared/authScene/RegionField'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import { OtherRegionHint } from 'scenes/authentication/shared/OtherRegionHint'
import { RedirectIfLoggedInOtherInstance } from 'scenes/authentication/shared/RedirectToLoggedInInstance'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { LoginMethod } from '~/types'

import { loginLogic } from './loginLogic'
import { SessionRiskBanner } from './SessionRiskBanner'

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

// Bare text nodes below are wrapped in <span>s: in-page translation replaces text nodes with
// <font> elements, which crashes React's sibling insert/remove operations (removeChild /
// insertBefore NotFoundError, see react#11538). Text that is its own element's only child is
// already safe, so only text sharing a parent with element siblings needs wrapping.
export function LoginForm(): JSX.Element {
    const { precheck, exitCodeVerification, resendCodeBasedVerification } = useActions(loginLogic)
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
        codeVerificationRequired,
        isCodeVerificationSubmitting,
        isPasswordLoginUnavailable,
        hasNoConfiguredLoginMethod,
        restrictToProviders,
        autoRedirectingToProvider,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const isPasswordHidden = !!precheckResponse.sso_enforcement || isPasswordLoginUnavailable
    const isCodeSent = codeVerificationRequired
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
            <span>New to PostHog?</span>{' '}
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
        <AuthScene notes={['// welcome back', '// 500,000+ teams ship here']}>
            {preflight?.cloud && <RedirectIfLoggedInOtherInstance />}
            <AuthSceneCard footer={footer}>
                <AuthCardTitle
                    title={
                        isCodeSent ? (
                            'Enter your login code'
                        ) : (
                            <>
                                {/* This whole fragment is deleted when the title flips to the code-sent
                                    string, so even the separator space lives inside an element */}
                                <span>{'Log in to '}</span>
                                <span className="px-1 rounded-md bg-[color-mix(in_srgb,var(--color-blue-500)_10%,transparent)] text-[var(--color-blue-500)]">
                                    @PostHog
                                </span>
                            </>
                        )
                    }
                    sub={isCodeSent ? undefined : "Welcome back. Let's go ship something."}
                />
                <SessionRiskBanner className="mb-4" />
                {generalError && (
                    <div
                        className={twMerge(
                            'mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded',
                            isCodeSent ? 'bg-success-highlight border-success' : 'bg-danger-highlight border-danger'
                        )}
                    >
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
                                        openSupportForm({
                                            kind: 'support',
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
                {isCodeSent ? (
                    <Form
                        logic={loginLogic}
                        formKey="codeVerification"
                        enableFormOnSubmit
                        className="flex flex-col gap-4"
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
                        <div className="flex flex-col items-center gap-3">
                            <LemonButton
                                size="small"
                                type="tertiary"
                                disabled={resendResponseLoading}
                                loading={resendResponseLoading}
                                onClick={() => resendCodeBasedVerification(null)}
                            >
                                Resend code
                            </LemonButton>
                            {resendResponse?.success && (
                                <p className="flex items-center gap-1 text-success mb-0" role="status">
                                    <IconCheckCircle />
                                    <span>Code sent — check your inbox.</span>
                                </p>
                            )}
                            <Link
                                onClick={() => exitCodeVerification()}
                                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary"
                            >
                                Back to login
                            </Link>
                        </div>
                    </Form>
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
                                    // `autoAttempt` is only ever set on this explicit gesture, so
                                    // autofill or a mistyped address can't bounce the user out to an
                                    // identity provider.
                                    onBlur={() => precheck({ email: login.email, autoAttempt: true })}
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
                        {hasNoConfiguredLoginMethod && (
                            <div className="py-2.5 px-3 text-sm leading-normal text-primary text-left bg-warning-highlight border border-warning rounded">
                                <span>No sign-in method is set up for this account. Use</span>{' '}
                                <Link
                                    to={[urls.passwordReset(), { email: login.email }]}
                                    data-attr="forgot-password"
                                    className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                                >
                                    Forgot password?
                                </Link>{' '}
                                <span>to set a password by email.</span>
                            </div>
                        )}
                        {autoRedirectingToProvider && (
                            <p className="text-sm text-secondary text-center mb-0">
                                Redirecting to {SSO_PROVIDER_NAMES[autoRedirectingToProvider]}…
                            </p>
                        )}
                        {/* No password to submit means this button would do nothing */}
                        {!precheckResponse.sso_enforcement && !isPasswordLoginUnavailable && (
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
                {/* Normally SAML replaces this row, but when the account has no password we need to
                    show whatever it does have. */}
                {!isCodeSent &&
                    !precheckResponse.sso_enforcement &&
                    (!precheckResponse.saml_available || isPasswordLoginUnavailable) && (
                        <SocialLoginButtons
                            topDivider
                            caption={isPasswordLoginUnavailable ? 'Log in with' : 'Or log in with'}
                            captionLocation="top"
                            lastUsedProvider={lastLoginMethod}
                            restrictToProviders={restrictToProviders}
                            // Once we know the account's methods, only offer a passkey if it actually has
                            // one — otherwise this is the same dead button we're removing.
                            showPasskey={!isPasswordLoginUnavailable || !!precheckResponse.webauthn_credentials?.length}
                        />
                    )}
            </AuthSceneCard>
        </AuthScene>
    )
}

import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { IconCheckCircle } from '@posthog/icons'

import { getCookie } from 'lib/api'
import { pngHoggie } from 'lib/brand/hoggies'
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
import { isValidVerificationCode, normalizeVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { LoginMethod, Region, SSOProvider } from '~/types'

import { loginLogic } from './loginLogic'
import { SessionRiskBanner } from './SessionRiskBanner'

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

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

// Bare text nodes below are wrapped in <span>s: in-page translation replaces text nodes with
// <font> elements, which crashes React's sibling insert/remove operations (removeChild /
// insertBefore NotFoundError, see react#11538). Text that is its own element's only child is
// already safe, so only text sharing a parent with element siblings needs wrapping.
export function LoginForm(): JSX.Element {
    const { precheck, exitCodeVerification, resendCodeBasedVerification, submitCodeVerification } =
        useActions(loginLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { sendSupportRequest } = useValues(supportLogic)
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
        codeVerificationEmail,
        codeVerification,
        hasNoConfiguredLoginMethod,
        restrictToProviders,
        autoRedirectingToProvider,
        availableLoginMethods,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const openLoginSupportForm = (errorCode?: string): void => {
        // Trust the precheck only when it resolved for the email now in the form: a failed
        // precheck reports permissive defaults, and a stale one still holds the previous email's
        // account.
        const precheckTrusted =
            precheckResponse.status === 'completed' &&
            !precheckResponse.precheckFailed &&
            precheckResponse.email === login.email
        openSupportForm({
            kind: 'support',
            email: login.email,
            // Prefill only into an empty form. Passing no message lets openSupportForm keep a
            // draft the person already started, so reopening this link never overwrites their text.
            message: sendSupportRequest.message
                ? undefined
                : buildLoginSupportMessage({
                      errorCode,
                      region: preflight?.region,
                      ssoEnforcement: precheckResponse.sso_enforcement,
                      availableLoginMethods,
                      precheckTrusted,
                      codeVerificationPending: codeVerificationRequired,
                  }),
        })
    }

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
                {isCodeSent && <HedgehogMagnifyingGlass className="block w-auto mx-auto mb-3 h-28" />}
                <AuthCardTitle
                    className={isCodeSent ? 'mb-2' : undefined}
                    title={
                        isCodeSent ? (
                            'Check your inbox'
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
                    sub={
                        isCodeSent ? (
                            <>
                                For your security, we've emailed a 6-digit verification code to{' '}
                                <strong>{codeVerificationEmail}</strong>.
                            </>
                        ) : (
                            "Welcome back. Let's go ship something."
                        )
                    }
                />
                <SessionRiskBanner className="mb-4" />
                {isCodeSent && (
                    <div className="mb-5 flex flex-col items-center gap-1 text-sm">
                        <Link
                            onClick={() => resendCodeBasedVerification(null)}
                            disabledReason={resendResponseLoading ? 'Sending...' : undefined}
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary"
                        >
                            Resend code
                        </Link>
                        {resendResponse?.success && (
                            <p className="flex items-center gap-1 text-success mb-0" role="status">
                                <IconCheckCircle />
                                <span>Code sent</span>
                            </p>
                        )}
                        <p className="text-secondary text-center text-balance mb-0">
                            <span>No code yet? Check your spam folder.</span>
                            {preflight?.cloud && (
                                <>
                                    {' '}
                                    <Link
                                        data-attr="login-code-contact-support"
                                        onClick={(e) => {
                                            e.preventDefault()
                                            openLoginSupportForm()
                                        }}
                                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                                    >
                                        Still stuck? Get help
                                    </Link>
                                </>
                            )}
                        </p>
                    </div>
                )}
                {generalError && (
                    <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
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
                                        openLoginSupportForm(generalError.code)
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
                        // The code input renders a hidden input with a \d{6} pattern. Without noValidate,
                        // the browser blocks submit on a partial code and kea cannot show its error.
                        noValidate
                        className="flex flex-col gap-4"
                    >
                        <LemonField
                            name="code"
                            label="Verification code"
                            labelClassName="sr-only"
                            // Plain centered text without an icon, like the signup verify screen's error
                            renderError={(error) => (
                                <p className="m-0 text-sm text-danger text-center" role="alert">
                                    {error}
                                </p>
                            )}
                        >
                            <VerificationCodeInput
                                data-attr="code-verification"
                                disabled={isCodeVerificationSubmitting}
                                onComplete={() => {
                                    if (!isCodeVerificationSubmitting) {
                                        submitCodeVerification()
                                    }
                                }}
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
                            disabledReason={
                                isValidVerificationCode(normalizeVerificationCode(codeVerification.code))
                                    ? undefined
                                    : 'Enter the 6-digit code from your email'
                            }
                        >
                            Verify and log in
                        </LemonButton>
                        <div className="flex flex-col items-center gap-3">
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

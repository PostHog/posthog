import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCheckCircle } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { SocialLoginButtons, SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'
import { OtherRegionHint } from 'scenes/authentication/shared/OtherRegionHint'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { isValidVerificationCode, normalizeVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'
import { urls } from 'scenes/urls'

import { authLogic } from '../authLogic'
import { ConnectTitle } from '../components/ConnectTitle'
import { LoginErrorBanner } from '../components/LoginErrorBanner'
import { UseDifferentEmailLink } from '../components/UseDifferentEmailLink'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

function LoginStepTitle(): JSX.Element {
    const { login, codeVerificationEmail, codeVerificationRequired, precheckResponse } = useValues(loginLogic)
    const { entry } = useValues(authLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)
    const isNewAccount = precheckResponse.account_exists === false

    if (codeVerificationRequired) {
        return (
            <AuthCardTitle
                className="mb-2"
                title="Check your inbox"
                sub={
                    <>
                        For your security, we've emailed a 6-digit verification code to{' '}
                        <strong>{codeVerificationEmail}</strong>.
                    </>
                }
            />
        )
    }

    const greeting = isNewAccount ? (
        <>
            <span>Nice to meet you,</span> <span className="AuthScene__mono">{login.email}</span>
            <span>.</span>
        </>
    ) : entry === 'signup' ? (
        <>
            <span>Plot twist:</span> <span className="AuthScene__mono">{login.email}</span>{' '}
            <span>already has an account.</span>
        </>
    ) : (
        <>
            <span>Good to see you,</span> <span className="AuthScene__mono">{login.email}</span>
            <span>.</span>
        </>
    )
    if (pendingConnection) {
        return (
            <AuthCardTitle
                title={<ConnectTitle lead="Log in to connect" clientName={pendingConnection.clientName} />}
                sub={greeting}
            />
        )
    }
    return <AuthCardTitle title={isNewAccount ? 'Your team uses single sign-on' : 'Welcome back'} sub={greeting} />
}

export function LoginStep(): JSX.Element {
    const { exitCodeVerification, resendCodeBasedVerification, submitCodeVerification } = useActions(loginLogic)
    const { chooseAccountPath } = useActions(authLogic)
    const {
        precheckResponse,
        login,
        isLoginSubmitting,
        generalError,
        resendResponseLoading,
        resendResponse,
        isCodeVerificationSubmitting,
        isPasswordLoginUnavailable,
        codeVerification,
        hasNoConfiguredLoginMethod,
        restrictToProviders,
        autoRedirectingToProvider,
        codeVerificationRequired: isCodeSent,
    } = useValues(loginLogic)
    const lastLoginMethod = useLastLoginMethod()

    // A new person reaches this step only on a SAML or OIDC domain, where the IdP creates the account
    const isNewAccount = precheckResponse.account_exists === false
    const isPasswordHidden = !!precheckResponse.sso_enforcement || isPasswordLoginUnavailable || isNewAccount

    return (
        <AuthSceneCard footer={isCodeSent ? undefined : <UseDifferentEmailLink />}>
            {isCodeSent && <HedgehogMagnifyingGlass className="block w-auto mx-auto mb-3 h-28" />}
            <LoginStepTitle />
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
                </div>
            )}
            <LoginErrorBanner />
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
                    {/* Password managers pair the saved password with this username */}
                    <input type="email" name="email" autoComplete="username" value={login.email} readOnly hidden />
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
                                    autoFocus
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
                                // Autocapture reports the click. Each reset entry point has its
                                // own `data-attr`, so one funnel can tell them apart.
                                data-attr="login-no-method-reset-password"
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
                    {!isPasswordHidden && (
                        <LemonButton
                            type="primary"
                            size="large"
                            center
                            fullWidth
                            htmlType="submit"
                            data-attr="password-login"
                            loading={isLoginSubmitting}
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
                    {precheckResponse.oidc_available && !precheckResponse.sso_enforcement && (
                        <SSOEnforcedLoginButton
                            provider="oidc"
                            email={login.email}
                            isLastUsed={lastLoginMethod === 'oidc'}
                        />
                    )}
                </Form>
            )}
            {/* Normally SAML replaces this row, but when the account has no password we need to
                show whatever it does have. */}
            {isNewAccount && !precheckResponse.sso_enforcement && (
                <p className="mt-4 mb-0 text-sm text-secondary text-center">
                    <Link
                        onClick={() => chooseAccountPath('signup', false)}
                        data-attr="auth-sso-domain-signup-with-email"
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                    >
                        Sign up with email instead
                    </Link>
                </p>
            )}
            {!isCodeSent &&
                !isNewAccount &&
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
    )
}

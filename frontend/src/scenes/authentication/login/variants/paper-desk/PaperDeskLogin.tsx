import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useState } from 'react'

import { getCookie } from 'lib/api'
import { SocialLoginButtons, SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import { CardTitle } from 'scenes/authentication/shared/paperDesk/CardTitle'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { RegionField } from 'scenes/authentication/shared/paperDesk/RegionField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { LoginMethod } from '~/types'

import { loginLogic } from '../../loginLogic'

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

function Login(): JSX.Element {
    const { precheck, clearGeneralError, resendEmailMFA, devLogin, loadDevUsers } = useActions(loginLogic)
    const {
        precheckResponse,
        precheckResponseLoading,
        login,
        isLoginSubmitting,
        generalError,
        signupUrl,
        resendResponseLoading,
        devUsers,
        devUsersLoading,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)
    const allowDevLogin = !!preflight?.allow_dev_login

    const isPasswordHidden = !!precheckResponse.sso_enforcement
    const isEmailVerificationSent = generalError?.code === 'email_verification_sent'
    const lastLoginMethod = getCookie(LAST_LOGIN_METHOD_COOKIE) as LoginMethod
    const [devLoginOpen, setDevLoginOpen] = useState(false)

    useEffect(() => {
        if (allowDevLogin) {
            loadDevUsers(null)
        }
    }, [allowDevLogin, loadDevUsers])

    const footer = (
        <p className="mt-5 mb-0 text-sm text-secondary text-center">
            New to PostHog?{' '}
            <Link
                to={signupUrl}
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                Create an account →
            </Link>
        </p>
    )

    return (
        <PaperDeskScene notes={['// welcome back', '// 100,000+ teams ship here']}>
            <PaperDeskCard footer={footer}>
                <CardTitle
                    title={isEmailVerificationSent ? 'Check your email' : 'Log in to PostHog'}
                    sub={isEmailVerificationSent ? undefined : "Welcome back. Let's go ship something."}
                />
                {generalError && (
                    <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
                        {generalError.detail ||
                            ERROR_MESSAGES[generalError.code] ||
                            'Could not complete your login. Please try again.'}
                    </div>
                )}
                {isEmailVerificationSent ? (
                    <div className="flex flex-col items-center gap-3">
                        <LemonButton
                            size="large"
                            center
                            fullWidth
                            disabled={resendResponseLoading}
                            loading={resendResponseLoading}
                            onClick={() => resendEmailMFA(null)}
                        >
                            Resend verification email
                        </LemonButton>
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
                                    type="email"
                                    autoFocus
                                    placeholder="you@yourcompany.com"
                                    autoComplete="email"
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
                                            to={urls.passwordReset()}
                                            className="text-xs font-semibold text-muted"
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
                {allowDevLogin && !devUsersLoading && devUsers.length > 0 && (
                    <div className="mt-5 border-t border-dashed pt-4">
                        <button
                            type="button"
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary text-xs"
                            onClick={() => setDevLoginOpen((open) => !open)}
                            aria-expanded={devLoginOpen}
                        >
                            {devLoginOpen ? '▾' : '▸'} Dev login ({devUsers.length}) · development only
                        </button>
                        {devLoginOpen && (
                            <div className="mt-2 flex flex-col gap-1">
                                {devUsers.map((u) => (
                                    <LemonButton
                                        key={u.email}
                                        fullWidth
                                        onClick={() => devLogin(u.email)}
                                        data-attr={`dev-login-${u.email}`}
                                    >
                                        {u.email}
                                    </LemonButton>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

export { Login as PaperDeskLogin }

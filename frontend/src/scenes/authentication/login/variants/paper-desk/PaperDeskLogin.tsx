import { useActions, useValues } from 'kea'
import { Form, Field as FormField } from 'kea-forms'
import { type ChangeEvent, useEffect, useState } from 'react'

import { getCookie } from 'lib/api'
import { SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import {
    PaperCardTitle,
    PaperDivider,
    PaperField,
    PaperFooterNote,
    PaperInput,
    PaperLink,
    PaperPrimaryButton,
    PaperRegionField,
    PaperSecondaryButton,
    PaperSocialIcons,
} from 'scenes/authentication/shared/paperDesk/PaperDeskControls'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'
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
    const { beginPasskeyLogin } = useActions(passkeyLogic)
    const { preflight } = useValues(preflightLogic)
    const allowDevLogin = !!preflight?.allow_dev_login

    // Show the password field upfront (matching the design); only hide it when SSO is enforced.
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
        <PaperFooterNote>
            New to PostHog? <PaperLink to={signupUrl}>Create an account →</PaperLink>
        </PaperFooterNote>
    )

    return (
        <PaperDeskScene notes={['// welcome back', '// 100,000+ teams ship here']}>
            <PaperDeskCard footer={footer}>
                <PaperCardTitle
                    title={isEmailVerificationSent ? 'Check your email' : 'Log in to PostHog'}
                    sub={isEmailVerificationSent ? undefined : "Welcome back. Let's go ship something."}
                />
                {generalError && (
                    <div className="PaperDesk__error mb-4">
                        {generalError.detail ||
                            ERROR_MESSAGES[generalError.code] ||
                            'Could not complete your login. Please try again.'}
                    </div>
                )}
                {isEmailVerificationSent ? (
                    <div className="flex flex-col items-center gap-3">
                        <PaperSecondaryButton disabled={resendResponseLoading} onClick={() => resendEmailMFA(null)}>
                            Resend verification email
                        </PaperSecondaryButton>
                        <PaperLink muted onClick={() => clearGeneralError()}>
                            Back to login
                        </PaperLink>
                    </div>
                ) : (
                    <Form logic={loginLogic} formKey="login" enableFormOnSubmit className="flex flex-col gap-4">
                        <PaperRegionField />
                        <FormField name="email">
                            {({ value, onChange, error, id }) => (
                                <PaperField label="Email" help={error} helpError={!!error}>
                                    <PaperInput
                                        id={id}
                                        type="email"
                                        autoFocus
                                        placeholder="you@yourcompany.com"
                                        autoComplete="email"
                                        value={value ?? ''}
                                        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                        onBlur={() => precheck({ email: login.email })}
                                        invalid={!!error}
                                    />
                                </PaperField>
                            )}
                        </FormField>
                        {!isPasswordHidden && (
                            <FormField name="password">
                                {({ value, onChange, error, id }) => (
                                    <PaperField
                                        label="Password"
                                        help={error}
                                        helpError={!!error}
                                        right={
                                            <PaperLink
                                                to={urls.passwordReset()}
                                                className="text-[12.5px]"
                                                tabIndex={-1}
                                            >
                                                Forgot password?
                                            </PaperLink>
                                        }
                                    >
                                        <PaperInput
                                            id={id}
                                            type="password"
                                            placeholder="••••••••••"
                                            autoComplete="current-password"
                                            value={value ?? ''}
                                            onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                            invalid={!!error}
                                        />
                                    </PaperField>
                                )}
                            </FormField>
                        )}
                        {!precheckResponse.sso_enforcement && (
                            <PaperPrimaryButton
                                loading={isLoginSubmitting || precheckResponseLoading}
                                loadingLabel="Logging in…"
                            >
                                Log in
                            </PaperPrimaryButton>
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
                    <>
                        <PaperDivider dashed label="Or log in with" />
                        <PaperSocialIcons
                            verb="Log in"
                            lastUsed={lastLoginMethod}
                            showPasskey
                            onPasskey={() => beginPasskeyLogin(undefined, undefined)}
                        />
                    </>
                )}
                {allowDevLogin && !devUsersLoading && devUsers.length > 0 && (
                    <div className="mt-5 border-t border-dashed pt-4">
                        <button
                            type="button"
                            className="PaperDesk__link PaperDesk__link--muted text-xs"
                            onClick={() => setDevLoginOpen((open) => !open)}
                            aria-expanded={devLoginOpen}
                        >
                            {devLoginOpen ? '▾' : '▸'} Dev login ({devUsers.length}) · development only
                        </button>
                        {devLoginOpen && (
                            <div className="mt-2 flex flex-col gap-1">
                                {devUsers.map((u) => (
                                    <PaperSecondaryButton
                                        key={u.email}
                                        onClick={() => devLogin(u.email)}
                                        data-attr={`dev-login-${u.email}`}
                                    >
                                        {u.email}
                                    </PaperSecondaryButton>
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

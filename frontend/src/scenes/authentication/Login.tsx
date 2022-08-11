import React from 'react'
import './Login.scss'
import { useActions, useValues } from 'kea'
import { loginLogic } from './loginLogic'
import { Link } from 'lib/components/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import clsx from 'clsx'
import { WelcomeLogo } from './WelcomeLogo'
import { SceneExport } from 'scenes/sceneTypes'
import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SSOProviders } from '~/types'
import { LemonButton, LemonButtonProps, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'

export const ERROR_MESSAGES: Record<string, string | JSX.Element> = {
    no_new_organizations:
        'Your email address is not associated with an account. Please ask your administrator for an invite.',
    invalid_sso_provider: (
        <>
            The SSO provider you specified is invalid. Visit{' '}
            <a href="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </a>{' '}
            for details.
        </>
    ),
    improperly_configured_sso: (
        <>
            Cannot login with SSO provider because the provider is not configured, or your instance does not have the
            required license. Please visit{' '}
            <a href="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </a>{' '}
            for details.
        </>
    ),
    jit_not_enabled:
        'We could not find an account with your email address and your organization does not support automatic enrollment. Please contact your administrator for an invite.',
}

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

function SSOLoginButton({
    email,
    provider,
    status = 'primary',
}: {
    email: string
    provider: SSOProviders
    status?: LemonButtonProps['status']
}): JSX.Element {
    return (
        <LemonButton
            className="btn-bridge"
            data-attr="sso-login"
            htmlType="button"
            fullWidth
            onClick={() => (window.location.href = `/login/${provider}/?email=${email}`)}
            icon={SocialLoginIcon(provider)}
            status={status}
        >
            Login with {SSO_PROVIDER_NAMES[provider]}
        </LemonButton>
    )
}

export function Login(): JSX.Element {
    const { precheck } = useActions(loginLogic)
    const { precheckResponse, precheckResponseLoading, loginForm, isLoginFormSubmitting, loginFormManualErrors } =
        useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <div className="bridge-page login">
            <div className="auth-main-content">
                <WelcomeLogo view="login" />
                <div className="inner space-y-2">
                    <h2 className="subtitle justify-center">Get started</h2>
                    {loginFormManualErrors.generic && (
                        <AlertMessage type="error">
                            {loginFormManualErrors.generic.errorDetail ||
                                ERROR_MESSAGES[loginFormManualErrors.generic.errorCode] ||
                                'Could not complete your login. Please try again.'}
                        </AlertMessage>
                    )}
                    <Form logic={loginLogic} formKey={'loginForm'} enableFormOnSubmit className="space-y-2">
                        <Field name="email" label="Email">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus
                                data-attr="login-email"
                                placeholder="email@yourcompany.com"
                                type="email"
                                onBlur={() => precheck({ email: loginForm.email })}
                                onPressEnter={() => {
                                    precheck({ email: loginForm.email })
                                    document.getElementById('password')?.focus()
                                }}
                                autoComplete="off"
                            />
                        </Field>
                        <div
                            className={clsx(
                                'password-wrapper',
                                (precheckResponse.status === 'pending' || precheckResponse.sso_enforcement) && 'hidden'
                            )}
                        >
                            <Field name="password" label="Password">
                                <LemonInput
                                    type="password"
                                    className="ph-ignore-input"
                                    data-attr="password"
                                    placeholder="••••••••••"
                                />
                            </Field>
                        </div>
                        {precheckResponse.status === 'pending' || !precheckResponse.sso_enforcement ? (
                            <LemonButton
                                htmlType="submit"
                                data-attr="password-login"
                                fullWidth
                                type="primary"
                                status="primary-alt"
                                center
                                loading={isLoginFormSubmitting || precheckResponseLoading}
                            >
                                Login
                            </LemonButton>
                        ) : (
                            <SSOLoginButton provider={precheckResponse.sso_enforcement} email={loginForm.email} />
                        )}
                        {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                            <SSOLoginButton provider="saml" email={loginForm.email} status="primary" />
                        )}
                    </Form>
                    <div className="helper-links">
                        {preflight?.cloud && (
                            <Link to="/signup" data-attr="signup">
                                Create an account
                            </Link>
                        )}
                        <Link to="/reset" data-attr="forgot-password">
                            Forgot your password?
                        </Link>
                    </div>
                    <SocialLoginButtons caption="Or log in with" />
                </div>
            </div>
        </div>
    )
}

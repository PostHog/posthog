import { useEffect, useRef } from 'react'
import './Login.scss'
import { useActions, useValues } from 'kea'
import { loginLogic } from './loginLogic'
import { Link } from 'lib/components/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton'
import clsx from 'clsx'
import { SceneExport } from 'scenes/sceneTypes'
import { SocialLoginIcon } from 'lib/components/SocialLoginButton/SocialLoginIcon'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { SSOProviders } from '~/types'
import { LemonButton, LemonButtonProps, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import RegionSelect from './RegionSelect'

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
    const { precheckResponse, precheckResponseLoading, login, isLoginSubmitting, generalError } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const passwordInputRef = useRef<HTMLInputElement>(null)
    const isPasswordHidden = precheckResponse.status === 'pending' || precheckResponse.sso_enforcement

    useEffect(() => {
        if (!isPasswordHidden) {
            passwordInputRef.current?.focus()
        }
    }, [isPasswordHidden])

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
        >
            <div className="space-y-2">
                <h2>Log in</h2>
                {generalError && (
                    <AlertMessage type="error">
                        {generalError.detail ||
                            ERROR_MESSAGES[generalError.code] ||
                            'Could not complete your login. Please try again.'}
                    </AlertMessage>
                )}
                <Form logic={loginLogic} formKey="login" enableFormOnSubmit className="space-y-4">
                    <RegionSelect />
                    <Field name="email" label="Email">
                        <LemonInput
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="login-email"
                            placeholder="email@yourcompany.com"
                            type="email"
                            onBlur={() => precheck({ email: login.email })}
                            onPressEnter={() => {
                                precheck({ email: login.email })
                            }}
                        />
                    </Field>
                    <div className={clsx('PasswordWrapper', isPasswordHidden && 'zero-height')}>
                        <Field
                            name="password"
                            label={
                                <div className="flex flex-1 items-center justify-between gap-2">
                                    <span>Password</span>
                                    <Link to="/reset" data-attr="forgot-password">
                                        Forgot your password?
                                    </Link>
                                </div>
                            }
                        >
                            <LemonInput
                                type="password"
                                ref={passwordInputRef}
                                className="ph-ignore-input"
                                data-attr="password"
                                placeholder="••••••••••"
                                autoComplete="current-password"
                            />
                        </Field>
                    </div>
                    {precheckResponse.status === 'pending' || !precheckResponse.sso_enforcement ? (
                        <LemonButton
                            htmlType="submit"
                            data-attr="password-login"
                            fullWidth
                            type="primary"
                            center
                            loading={isLoginSubmitting || precheckResponseLoading}
                        >
                            Login
                        </LemonButton>
                    ) : (
                        <SSOLoginButton provider={precheckResponse.sso_enforcement} email={login.email} />
                    )}
                    {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                        <SSOLoginButton provider="saml" email={login.email} status="primary" />
                    )}
                </Form>
                {preflight?.cloud && (
                    <div className="text-center mt-4">
                        Don't have an account?{' '}
                        <Link to="/signup" data-attr="signup" className="font-bold">
                            Create an account
                        </Link>
                    </div>
                )}
                <SocialLoginButtons caption="Or log in with" topDivider />
            </div>
        </BridgePage>
    )
}

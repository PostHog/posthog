import './Login.scss'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SocialLoginButtons, SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { useEffect, useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { loginLogic } from './loginLogic'
import { redirectIfLoggedInOtherInstance } from './redirectToLoggedInInstance'
import RegionSelect from './RegionSelect'
import { SupportModalButton } from './SupportModalButton'

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
}

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

export function Login(): JSX.Element {
    const { precheck } = useActions(loginLogic)
    const { precheckResponse, precheckResponseLoading, login, isLoginSubmitting, generalError } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const passwordInputRef = useRef<HTMLInputElement>(null)
    const isPasswordHidden = precheckResponse.status === 'pending' || precheckResponse.sso_enforcement

    useEffect(() => {
        if (preflight?.cloud) {
            try {
                redirectIfLoggedInOtherInstance()
            } catch (e) {
                captureException(e)
            }
        }
    }, [])

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
            footer={<SupportModalButton />}
        >
            <div className="space-y-4">
                <h2>Log in</h2>
                {generalError && (
                    <LemonBanner type="error">
                        {generalError.detail || ERROR_MESSAGES[generalError.code] || (
                            <>
                                Could not complete your login.
                                <br />
                                Please try again.
                            </>
                        )}
                    </LemonBanner>
                )}
                <Form logic={loginLogic} formKey="login" enableFormOnSubmit className="space-y-4">
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
                                precheck({ email: login.email })
                                if (isPasswordHidden) {
                                    e.preventDefault() // Don't trigger submission if password field is still hidden
                                    passwordInputRef.current?.focus()
                                }
                            }}
                        />
                    </LemonField>
                    <div className={clsx('PasswordWrapper', isPasswordHidden && 'zero-height')}>
                        <LemonField
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
                                inputRef={passwordInputRef}
                                className="ph-ignore-input"
                                data-attr="password"
                                placeholder="••••••••••"
                                autoComplete="current-password"
                            />
                        </LemonField>
                    </div>
                    {precheckResponse.status === 'pending' || !precheckResponse.sso_enforcement ? (
                        <LemonButton
                            type="primary"
                            status="alt"
                            htmlType="submit"
                            data-attr="password-login"
                            fullWidth
                            center
                            loading={isLoginSubmitting || precheckResponseLoading}
                            size="large"
                        >
                            Log in
                        </LemonButton>
                    ) : (
                        <SSOEnforcedLoginButton provider={precheckResponse.sso_enforcement} email={login.email} />
                    )}
                    {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                        <SSOEnforcedLoginButton provider="saml" email={login.email} />
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
                {!precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                    <SocialLoginButtons caption="Or log in with" topDivider />
                )}
            </div>
        </BridgePage>
    )
}

import { LemonButton, LemonInput, LemonModal, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useEffect } from 'react'

import { SocialLoginButtons, SSOEnforcedLoginButton } from '../SocialLoginButton/SocialLoginButton'
import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

export function TimeSensitiveAuthenticationModal(): JSX.Element {
    const {
        showAuthenticationModal,
        isReauthenticationSubmitting,
        twoFactorRequired,
        user,
        precheckResponse,
        precheckResponseLoading,
    } = useValues(timeSensitiveAuthenticationLogic)
    const { submitReauthentication, setDismissedReauthentication } = useActions(timeSensitiveAuthenticationLogic)

    const ssoEnforcement = precheckResponse?.sso_enforcement
    const showPassword = !ssoEnforcement && user?.has_password

    const extraQueryParams = {
        next: window.location.pathname,
    }

    return (
        <LemonModal
            title="Re-authenticate account"
            isOpen={showAuthenticationModal}
            onClose={() => setDismissedReauthentication(true)}
            maxWidth="30rem"
            footer={
                ssoEnforcement ? (
                    <span className="flex-1">
                        <SSOEnforcedLoginButton
                            provider={ssoEnforcement}
                            email={user!.email}
                            size="medium"
                            extraQueryParams={extraQueryParams}
                        />
                    </span>
                ) : showPassword ? (
                    <LemonButton
                        type="primary"
                        form="reauthentication"
                        loading={isReauthenticationSubmitting}
                        onClick={submitReauthentication}
                    >
                        Re-authenticate
                    </LemonButton>
                ) : undefined
            }
        >
            <p>You are accessing a sensitive part of PostHog. For your security we require you to re-authenticate.</p>

            {showPassword ? (
                <Form
                    logic={timeSensitiveAuthenticationLogic}
                    formKey="reauthentication"
                    className="space-y-4"
                    enableFormOnSubmit
                >
                    {!twoFactorRequired ? (
                        <LemonField name="password" label="Re-enter password">
                            <LemonInput
                                type="password"
                                className="ph-ignore-input"
                                data-attr="password"
                                autoComplete="current-password"
                            />
                        </LemonField>
                    ) : null}

                    {twoFactorRequired ? (
                        <LemonField name="token" label="Authenticator token">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus
                                data-attr="token"
                                placeholder="123456"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                            />
                        </LemonField>
                    ) : null}
                </Form>
            ) : null}

            {!ssoEnforcement ? (
                <div className="space-y-2">
                    <SocialLoginButtons
                        className="mt-4"
                        caption={showPassword ? 'Or re-authenticate with' : undefined}
                        extraQueryParams={extraQueryParams}
                    />
                    {precheckResponse?.saml_available ? (
                        <SSOEnforcedLoginButton
                            provider="saml"
                            email={user!.email}
                            size="medium"
                            extraQueryParams={extraQueryParams}
                        />
                    ) : null}
                </div>
            ) : null}
            {precheckResponseLoading && <SpinnerOverlay />}
        </LemonModal>
    )
}

export function TimeSensitiveAuthenticationArea({ children }: { children: JSX.Element }): JSX.Element {
    const { timeSensitiveAuthenticationRequired } = useValues(timeSensitiveAuthenticationLogic)
    const { setDismissedReauthentication, checkReauthentication } = useActions(timeSensitiveAuthenticationLogic)

    useEffect(() => {
        checkReauthentication()
    }, [])

    return timeSensitiveAuthenticationRequired ? (
        <div className="flex-1 bg-bg-3000 border border-border rounded flex flex-col items-center p-6 text-center w-full">
            <h2>Re-authentication required</h2>

            <p>For security purposes, this area requires that you re-authenticate</p>

            <LemonButton type="primary" onClick={() => setDismissedReauthentication(false)}>
                Re-authenticate
            </LemonButton>
        </div>
    ) : (
        children
    )
}

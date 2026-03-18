import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput, LemonModal, SpinnerOverlay } from '@posthog/lemon-ui'

import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SSOEnforcedLoginButton, SocialLoginButtons } from '../SocialLoginButton/SocialLoginButton'
import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

export function TimeSensitiveAuthenticationModal(): JSX.Element {
    const {
        showAuthenticationModal,
        isReauthenticationSubmitting,
        twoFactorRequired,
        user,
        precheckResponse,
        precheckResponseLoading,
        passkey2FALoading,
        passkeysAvailable,
        totpAvailable,
    } = useValues(timeSensitiveAuthenticationLogic)
    const { submitReauthentication, setDismissedReauthentication, beginPasskey2FA } = useActions(
        timeSensitiveAuthenticationLogic
    )

    const ssoEnforcement = precheckResponse?.sso_enforcement
    const showPassword = !ssoEnforcement && user?.has_password

    const extraQueryParams = {
        next: location.href.replace(location.origin, ''),
        email: user?.email || '',
        reauth: 'true',
    }

    return (
        <LemonModal
            zIndex="1169" // The re-authentication modal should be above the all popovers, including the AI consent popover
            title="Re-authenticate for security"
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
            <p>
                Before accessing and changing sensitive settings, we ask you to&nbsp;re-authenticate. Just to ensure you
                are you!
            </p>

            {showPassword ? (
                <Form
                    logic={timeSensitiveAuthenticationLogic}
                    formKey="reauthentication"
                    className="deprecated-space-y-4"
                    enableFormOnSubmit
                >
                    {!twoFactorRequired ? (
                        <LemonField name="password" label="Re-enter password">
                            <LemonInput
                                type="password"
                                className="ph-ignore-input"
                                data-attr="password"
                                autoComplete="current-password"
                                autoFocus
                            />
                        </LemonField>
                    ) : null}

                    {twoFactorRequired ? (
                        <>
                            {passkeysAvailable && (
                                <>
                                    <LemonButton
                                        type="primary"
                                        htmlType="button"
                                        onClick={() => beginPasskey2FA()}
                                        loading={passkey2FALoading}
                                        fullWidth
                                        center
                                        size="large"
                                        icon={
                                            <img src={passkeyLogo} alt="Passkey" className="object-contain w-6 h-6" />
                                        }
                                    >
                                        Use passkey
                                    </LemonButton>
                                    {totpAvailable && <LemonDivider className="my-4" label="Or" />}
                                </>
                            )}

                            {totpAvailable && (
                                <LemonField name="token" label="Authenticator token">
                                    <LemonInput
                                        className="ph-ignore-input"
                                        autoFocus={!passkeysAvailable}
                                        data-attr="token"
                                        placeholder="123456"
                                        inputMode="numeric"
                                        autoComplete="one-time-code"
                                    />
                                </LemonField>
                            )}

                            {!passkeysAvailable && !totpAvailable && (
                                <p className="text-muted">No 2FA methods available. Please contact support.</p>
                            )}
                        </>
                    ) : null}
                </Form>
            ) : null}

            {!ssoEnforcement ? (
                <div className="deprecated-space-y-2">
                    <SocialLoginButtons
                        className="mt-4"
                        caption={showPassword ? 'Or re-authenticate with' : undefined}
                        extraQueryParams={extraQueryParams}
                        showPasskey={true}
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
    useOnMountEffect(checkReauthentication)

    return timeSensitiveAuthenticationRequired ? (
        <div className="flex-1 bg-primary border border-primary rounded flex flex-col items-center p-6 text-center w-full">
            <h2>Re-authentication required</h2>

            <p>This area requires that you re-authenticate.</p>

            <LemonButton type="primary" onClick={() => setDismissedReauthentication(false)}>
                Re-authenticate
            </LemonButton>
        </div>
    ) : (
        children
    )
}

import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Suspense, lazy } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonModal, SpinnerOverlay } from '@posthog/lemon-ui'

import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { retryImport } from 'lib/utils/retryImport'

import { SSOEnforcedLoginButton, SocialLoginButtons } from '../SocialLoginButton/SocialLoginButton'
import { SetPasswordLinkPrompt } from './SetPasswordLinkPrompt'
import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

// This file ships on every logged-in page, and quill must load only where a page turns it on.
const QuillTimeSensitiveAuthenticationModal = lazy(() =>
    retryImport(() => import('./QuillTimeSensitiveAuthenticationModal')).then((m) => ({
        default: m.QuillTimeSensitiveAuthenticationModal,
    }))
)
const QuillReauthenticationRequired = lazy(() =>
    retryImport(() => import('./QuillReauthenticationRequired')).then((m) => ({
        default: m.QuillReauthenticationRequired,
    }))
)

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
    const { submitReauthentication, setDismissedReauthentication, beginPasskey2FA, beginSsoReauthentication } =
        useActions(timeSensitiveAuthenticationLogic)
    // A global modal sits outside every quill surface, so it follows the flag itself.
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const ssoEnforcement = precheckResponse?.sso_enforcement
    const showPassword = !ssoEnforcement && user?.has_password
    const showSetPasswordLink = !ssoEnforcement && user?.has_password === false

    const extraQueryParams = {
        next: location.href.replace(location.origin, ''),
        email: user?.email || '',
        reauth: 'true',
    }

    if (todayRailNav) {
        return (
            <Suspense fallback={null}>
                <QuillTimeSensitiveAuthenticationModal
                    showPassword={!!showPassword}
                    showSetPasswordLink={showSetPasswordLink}
                    extraQueryParams={extraQueryParams}
                />
            </Suspense>
        )
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
                            onProviderClick={beginSsoReauthentication}
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
                        // One child of the spaced form, so the hidden input does not push the password field down
                        <div>
                            {/* Password managers match a saved login by username, so a lone password field gets a generated password instead */}
                            <input
                                type="email"
                                name="email"
                                autoComplete="username"
                                value={user?.email || ''}
                                readOnly
                                tabIndex={-1}
                                aria-hidden
                                className="sr-only"
                            />
                            <LemonField name="password" label="Password">
                                <LemonInput
                                    type="password"
                                    className="ph-ignore-input"
                                    data-attr="password"
                                    autoComplete="current-password"
                                    autoFocus
                                />
                            </LemonField>
                        </div>
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
                        onProviderClick={beginSsoReauthentication}
                        showPasskey={true}
                    />
                    {precheckResponse?.saml_available ? (
                        <SSOEnforcedLoginButton
                            provider="saml"
                            email={user!.email}
                            size="medium"
                            extraQueryParams={extraQueryParams}
                            onProviderClick={beginSsoReauthentication}
                        />
                    ) : null}
                    {precheckResponse?.oidc_available ? (
                        <SSOEnforcedLoginButton
                            provider="oidc"
                            email={user!.email}
                            size="medium"
                            extraQueryParams={extraQueryParams}
                            onProviderClick={beginSsoReauthentication}
                        />
                    ) : null}
                </div>
            ) : null}
            {showSetPasswordLink ? <SetPasswordLinkPrompt /> : null}
            {precheckResponseLoading && <SpinnerOverlay />}
        </LemonModal>
    )
}

export function TimeSensitiveAuthenticationArea({ children }: { children: JSX.Element }): JSX.Element {
    const { timeSensitiveAuthenticationRequired } = useValues(timeSensitiveAuthenticationLogic)

    const { setDismissedReauthentication, checkReauthentication } = useActions(timeSensitiveAuthenticationLogic)
    useOnMountEffect(checkReauthentication)
    const quillSurface = useQuillSurface()

    const reauthenticate = (): void => setDismissedReauthentication(false)

    if (quillSurface && timeSensitiveAuthenticationRequired) {
        return (
            <Suspense fallback={null}>
                <QuillReauthenticationRequired onReauthenticate={reauthenticate} />
            </Suspense>
        )
    }

    return timeSensitiveAuthenticationRequired ? (
        <div className="w-full">
            <div className="max-w-3xl rounded border border-primary bg-primary p-8">
                <div className="flex flex-col items-start gap-4 text-left">
                    <div>
                        <h2 className="text-2xl font-semibold m-0 mb-4">Re-authentication required</h2>
                        <p className="m-0 text-base text-secondary">
                            This settings area contains sensitive information, so we need you to re-authenticate before
                            continuing.
                        </p>
                    </div>

                    <LemonButton type="primary" onClick={reauthenticate}>
                        Re-authenticate
                    </LemonButton>
                </div>
            </div>
        </div>
    ) : (
        children
    )
}

import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { login2FALogic } from './login2FALogic'

export function Login2FA(): JSX.Element {
    const {
        isTwofactortokenSubmitting,
        generalError,
        passkey2FALoading,
        passkeysAvailable,
        totpAvailable,
        twoFactorResetRequest,
        twoFactorResetRequestLoading,
    } = useValues(login2FALogic)
    const { beginPasskey2FA, requestTwoFactorReset } = useActions(login2FALogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    return (
        <BridgePage view="login">
            <div className="deprecated-space-y-2">
                <h2>Two-Factor Authentication</h2>
                <p>
                    Enter a token from your authenticator app, use your passkey, or enter a backup code.
                    {preflight?.cloud && (
                        <>
                            {' '}
                            <Link
                                data-attr="2fa-contact-support"
                                onClick={(e) => {
                                    e.preventDefault()
                                    openSupportForm({
                                        kind: 'support',
                                        target_area: 'login',
                                    })
                                }}
                            >
                                Need help?
                            </Link>
                        </>
                    )}
                </p>

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
                            icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-6 h-6" />}
                        >
                            Use passkey
                        </LemonButton>
                        {totpAvailable && <LemonDivider className="my-4" label="Or" />}
                    </>
                )}

                {totpAvailable && (
                    <Form
                        logic={login2FALogic}
                        formKey="twofactortoken"
                        enableFormOnSubmit
                        className="deprecated-space-y-4"
                    >
                        {generalError && <LemonBanner type="error">{generalError.detail}</LemonBanner>}
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
                        <LemonButton
                            type="primary"
                            status="alt"
                            htmlType="submit"
                            data-attr="2fa-login"
                            fullWidth
                            center
                            loading={isTwofactortokenSubmitting}
                            size="large"
                        >
                            Login
                        </LemonButton>
                    </Form>
                )}

                {!passkeysAvailable && !totpAvailable && (
                    <LemonBanner type="error">
                        No 2FA methods available. Please contact support if you believe this is an error.
                    </LemonBanner>
                )}

                {(passkeysAvailable || totpAvailable) && (
                    <>
                        <LemonDivider className="my-4" />
                        {twoFactorResetRequest?.success ? (
                            <LemonBanner type="success">
                                We've emailed you a link to reset your two-factor authentication. Follow it to regain
                                access, then set up 2FA again to keep your account secure.
                            </LemonBanner>
                        ) : (
                            <div className="deprecated-space-y-2">
                                {twoFactorResetRequest && !twoFactorResetRequest.success && (
                                    <LemonBanner type="error">
                                        {twoFactorResetRequest.error}
                                        {twoFactorResetRequest.requires_login && (
                                            <>
                                                {' '}
                                                <Link to={urls.login()}>Log in again</Link>
                                            </>
                                        )}
                                    </LemonBanner>
                                )}
                                <p className="text-sm text-secondary text-center mb-0">
                                    Lost access to your authenticator?
                                </p>
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    data-attr="2fa-reset-request"
                                    fullWidth
                                    center
                                    loading={twoFactorResetRequestLoading}
                                    onClick={() => requestTwoFactorReset()}
                                >
                                    Email me a reset link
                                </LemonButton>
                            </div>
                        )}
                    </>
                )}
            </div>
        </BridgePage>
    )
}

export const scene: SceneExport = {
    component: Login2FA,
    logic: login2FALogic,
}
